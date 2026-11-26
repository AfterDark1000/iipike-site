// Shared browser session for HPII admin pages on iipike.ru.
// The Worker verifies the HMAC session, owner identity and every protected operation.
// The GitHub OAuth access token and repository write credentials never enter this client.
export class HpiiAdminAuth {
  constructor(backendOrigin) {
    if (!/^https:\/\//.test(backendOrigin)) throw Error("HTTPS backend required");
    this.backend = new URL(backendOrigin).origin;
    // v2 is shared across all same-origin admin tabs and browser restarts.
    // v1 was tab-scoped: migrate a still-valid legacy session on first visit.
    this.storageKey = "hpii-admin-session-v2";
    this.legacyKey = "hpii-admin-session-v1";
  }
  _read(area, key) {
    try { return window[area].getItem(key); } catch (_) { return null; }
  }
  _remove(area, key) {
    try { window[area].removeItem(key); } catch (_) { /* Storage may be disabled. */ }
  }
  _validToken(value) {
    return typeof value === "string" && value.length <= 2500 &&
      /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value);
  }
  getToken() {
    const shared = this._read("localStorage", this.storageKey);
    if (this._validToken(shared)) return shared;
    if (shared) this._remove("localStorage", this.storageKey);
    const tab = this._read("sessionStorage", this.storageKey) ||
      this._read("sessionStorage", this.legacyKey);
    if (!this._validToken(tab)) {
      if (tab) this.logout();
      return null;
    }
    // Migration is best-effort; private browsing can disallow persistent storage.
    try {
      window.localStorage.setItem(this.storageKey, tab);
      this._remove("sessionStorage", this.storageKey);
      this._remove("sessionStorage", this.legacyKey);
    } catch (_) { /* Preserve existing tab session when storage is blocked. */ }
    return tab;
  }
  _saveToken(token) {
    if (!this._validToken(token)) throw Error("Неверный формат сессии");
    try {
      window.localStorage.setItem(this.storageKey, token);
      this._remove("sessionStorage", this.storageKey);
      this._remove("sessionStorage", this.legacyKey);
      return;
    } catch (_) { /* Fallback only if browser blocks persistent storage. */ }
    try {
      window.sessionStorage.setItem(this.storageKey, token);
      return;
    } catch (_) {
      throw Error("Браузер запретил сохранять сессию. Разреши хранение данных для iipike.ru.");
    }
  }
  logout() {
    this._remove("localStorage", this.storageKey);
    this._remove("sessionStorage", this.storageKey);
    this._remove("sessionStorage", this.legacyKey);
  }
  async login() {
    const popup=window.open(this.backend+"/auth/start","hpii-github-login","width=570,height=700");
    if(!popup) throw Error("Разреши всплывающее окно для входа через GitHub");
    return new Promise((resolve,reject)=>{
      function clear(){window.removeEventListener("message",receive)}
      const self=this;
      function receive(event){
        if(event.origin!==self.backend || event.source!==popup) return;
        if(event.data?.type==="hpii-auth-error" && event.data?.backend===self.backend &&
           typeof event.data.reason==="string" && /^[a-z_]{2,60}$/.test(event.data.reason)){
          clear();
          reject(new Error("GitHub: "+event.data.reason));
          return;
        }
        if(event.data?.type!=="hpii-auth" || event.data?.backend!==self.backend ||
           typeof event.data?.token!=="string" || !/^[A-Za-z0-9_.-]+$/.test(event.data.token)) return;
        clear();
        try { self._saveToken(event.data.token); }
        catch (error) { reject(error); return; }
        resolve(event.data.login);
      }
      window.addEventListener("message",receive);
      // No long-lived background polling: closing popup leaves the ordinary page unchanged.
    });
  }
  async fetchApi(path,options={}) {
    const token=this.getToken();
    if(!token) throw Error("Сначала войди через GitHub");
    const response=await fetch(this.backend+path,{
      ...options,headers:{"Authorization":"Bearer "+token,...options.headers},
      credentials:"omit",cache:"no-store"
    });
    const data=await response.json().catch(()=>({ok:false,error:"invalid_api_response"}));
    if(response.status===401)this.logout();
    if(!response.ok || !data.ok) throw Error(data.error||"Ошибка сервера");
    return data;
  }
  async session(){return this.fetchApi("/api/session")}
  async listEditorialFiles(kind){
    if(!["drafts","copyedits"].includes(kind))throw Error("Недопустимый список материалов");
    const result=await this.fetchApi("/api/editorial-files?kind="+encodeURIComponent(kind));
    if(!Array.isArray(result.entries))throw Error("Сервер вернул неверный список материалов");
    return result.entries;
  }
  async readEditorialRecord(path){
    if(typeof path!=="string"||!/^editorial_inbox\/(auto_drafts|auto_decisions|auto_covers|auto_cover_decisions|auto_handoffs|auto_copyedits|auto_copyedit_decisions|auto_copyedit_responses)\/[a-z0-9]+(?:-[a-z0-9]+)*(?:-r[1-9]\d*(?:-v[1-9]\d*)?)?\.json$/.test(path))
      throw Error("Недопустимый путь редакционного файла");
    return this.fetchApi("/api/editorial-record?path="+encodeURIComponent(path));
  }
  async reviewCopyedit(item,candidateSha,action,note=""){
    return this.fetchApi("/api/copyedit-review",{
      method:"POST",headers:{"content-type":"application/json"},
      body:JSON.stringify({article_id:item.article_id,revision:item.source_revision,version:item.copyedit_version,
        source_sha:item.source_draft_blob_sha,candidate_sha:candidateSha,action,note})
    });
  }
  async reviewCover(article,cover,action,note="") {
    return this.fetchApi("/api/cover-review",{
      method:"POST",headers:{"content-type":"application/json"},
      body:JSON.stringify({
        article_id:article.article_id,revision:article.revision,
        text_updated_at:article.updated_at,cover_version:cover.cover_version||1,
        image_blob_sha:cover.image_blob_sha,action,note
      })
    });
  }
  async uploadCover(article,file,headline,concept,coverVersion=1) {
    const data=new FormData();
    data.set("article_id",article.article_id);
    data.set("revision",String(article.revision));
    data.set("cover_version",String(coverVersion));
    data.set("updated_at",article.updated_at);
    data.set("headline",headline);
    data.set("concept",concept);
    data.set("file",file,file.name);
    return this.fetchApi("/api/cover-upload",{method:"POST",body:data});
  }
  async review(article,action,note=""){
    return this.fetchApi("/api/review",{
      method:"POST",headers:{"content-type":"application/json"},
      body:JSON.stringify({article_id:article.article_id,revision:article.revision,
        updated_at:article.updated_at,action,note})
    });
  }
}
