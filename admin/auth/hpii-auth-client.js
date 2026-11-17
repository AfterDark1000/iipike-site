// Client helper for a FUTURE activated backend. Not currently loaded by public /admin.
// Backend MUST verify OAuth identity and authorize every write; this module is only UX.
export class HpiiAdminAuth {
  constructor(backendOrigin) {
    if (!/^https:\/\//.test(backendOrigin)) throw Error("HTTPS backend required");
    this.backend = new URL(backendOrigin).origin;
    this.storageKey = "hpii-admin-session-v1";
  }
  getToken() { return sessionStorage.getItem(this.storageKey); }
  logout() { sessionStorage.removeItem(this.storageKey); }
  async login() {
    const popup=window.open(this.backend+"/auth/start","hpii-github-login","width=570,height=700");
    if(!popup) throw Error("Разреши всплывающее окно для входа через GitHub");
    return new Promise((resolve,reject)=>{
      function clear(){window.removeEventListener("message",receive)}
      const self=this;
      function receive(event){
        if(event.origin!==self.backend || event.source!==popup) return;
        if(event.data?.type!=="hpii-auth" || event.data?.backend!==self.backend ||
           typeof event.data?.token!=="string" || !/^[A-Za-z0-9_.-]+$/.test(event.data.token)) return;
        clear();
        sessionStorage.setItem(self.storageKey,event.data.token);
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
  async uploadCover(article,file,headline,concept) {
    const data=new FormData();
    data.set("article_id",article.article_id);
    data.set("revision",String(article.revision));
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
