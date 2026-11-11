/* Keep the last frame on screen until its 500 ms opacity transition finishes. */
class OverlayVisibility {
 constructor(stage, options={}) {
  this.stage=stage; this.delay=500; this.timer=null; this.wantsVisible=false;
  this.schedule=options.schedule||setTimeout; this.cancel=options.cancel||clearTimeout;
 }
 show() {
  if(this.wantsVisible)return;
  this.wantsVisible=true;
  if(this.timer!==null){this.cancel(this.timer);this.timer=null}
  this.stage.classList.remove('hidden');
  void this.stage.offsetWidth;
  this.stage.classList.add('is-visible');
 }
 hide() {
  this.wantsVisible=false;
  this.stage.classList.remove('is-visible');
  if(this.stage.classList.contains('hidden')||this.timer!==null)return;
  this.timer=this.schedule(()=>{this.timer=null;if(!this.wantsVisible)this.stage.classList.add('hidden')},this.delay);
 }
}
if(typeof module!=='undefined')module.exports={OverlayVisibility};
