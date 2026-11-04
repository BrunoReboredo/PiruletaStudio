"""Optional real-browser smoke check; run directly on Windows with Edge installed."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vendor.postmatch.app import preview_snapshot
from studio import Studio

ROOT = Path(__file__).resolve().parents[1]


def main():
    state = preview_snapshot(Studio())
    state['media'] = {}
    state['studio'] = dict(phase='game', revision=1, gameplay=True)
    state['config']['colors']['pink'] = '#00ff00'
    state['config']['colors']['yellow'] = '#0077ff'
    # Frozen result intentionally retains different colors.
    state['postmatch']['config']['colors']['pink'] = '#ff0000'
    program = (ROOT/'program.html').read_text(encoding='utf-8')
    program = program.replace('setTimeout(poll,50)', '')
    checks = '''
<script>
window.addEventListener('error',e=>document.body.dataset.error=e.message);
const wait=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{try{
 await wait(750);
 // Advance compositor animations explicitly in headless virtual time.
 for(let n=0;n<3;n++){if(blackAnimation)blackAnimation.finish();await wait(10)}
 if(getComputedStyle(document.getElementById('game')).opacity!=='1')throw Error('Initial game');
 let previous='game';
 for(const p of ['pre','stats','victory0','victory1','game','end']){
  const change=showScene(p),black=document.getElementById('fade');
  const outgoing=document.getElementById(previous);
  if(!outgoing.classList.contains('active'))throw Error('Outgoing replaced before black');
  if(blackAnimation.effect.getTiming().duration!==300)throw Error('Fade out duration');
  blackAnimation.pause();blackAnimation.currentTime=150;
  const darkening=Number(getComputedStyle(black).opacity);
  if(!(darkening>0&&darkening<1))throw Error('Missing darkening');
  blackAnimation.finish();await wait(10);
  blackAnimation.pause();
  if(blackAnimation.effect.getTiming().duration!==200)throw Error('Black hold duration');
  blackAnimation.currentTime=100;
  if(Number(getComputedStyle(black).opacity)!==1)throw Error('Black hold opacity');
  if(!outgoing.classList.contains('active'))throw Error('Replaced before hold finished');
  blackAnimation.finish();await wait(10);
  if(!document.getElementById(p).classList.contains('active'))throw Error('Missing switch at black');
  if(getComputedStyle(black).backgroundColor!=='rgb(0, 0, 0)')throw Error('Not black');
  blackAnimation.pause();blackAnimation.currentTime=0;
  if(Number(getComputedStyle(black).opacity)!==1)throw Error('Not fully black at midpoint');
  if(blackAnimation.effect.getTiming().duration!==300)throw Error('Fade in duration');
  blackAnimation.currentTime=150;
  const revealing=Number(getComputedStyle(black).opacity);
  if(!(revealing>0&&revealing<1))throw Error('Missing reveal');
  blackAnimation.finish();await change;
  if(Number(getComputedStyle(black).opacity)!==0)throw Error('Black layer remained');
  for(const id of ids){if(id!==p&&getComputedStyle(document.getElementById(id)).visibility!=='hidden')throw Error('Outgoing '+id)}
  if(p==='pre'&&document.getElementById('engine').paused)throw Error('Engine audio did not start in pre');
  if(p!=='pre'&&!document.getElementById('engine').paused)throw Error('Engine audio outside pre');
  previous=p;
 }
 const sample=await(await fetch('/state')).json(),overlay=document.getElementById('game').contentWindow;
 for(const [phase,gameplay,expected] of [['game',true,'visible'],['game',false,'hidden'],['pre',true,'hidden'],['stats',true,'hidden'],['victory0',true,'hidden'],['complete',true,'hidden']]){
  sample.studio={phase,gameplay};overlay.render(sample);
  if(overlay.getComputedStyle(overlay.document.getElementById('stage')).visibility!==expected)throw Error('Marker visibility '+phase+' '+gameplay);
 }
 sample.studio={phase:'game',gameplay:true};overlay.render(sample);
 const rect=id=>overlay.document.getElementById(id).getBoundingClientRect();
 if(Math.abs(rect('series0').left-rect('logo0').left)>1)throw Error('Left pips alignment');
 if(Math.abs(rect('series1').right-rect('logo1').right)>1)throw Error('Right pips alignment');
 const engine=document.getElementById('engine');
 if(engine.duration!==8)throw Error('Engine audio did not decode: '+engine.duration);
 const frame=document.getElementById('stats').contentDocument;
 const stage=frame.getElementById('stage');
 if(stage.style.getPropertyValue('--pink')!=='#00ff00')throw Error('Stats live color');
 if(stage.style.getPropertyValue('--yellow')!=='#0077ff')throw Error('Stats second color');
 document.body.dataset.qa='PASS';
}catch(e){document.body.dataset.qa='FAIL: '+e.message}})();
</script>
'''
    program = program.replace('</html>', checks+'</html>')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            route = self.path.split('?')[0]
            if route == '/state':
                data, kind = json.dumps(state).encode(), 'application/json'
            elif route == '/program':
                data, kind = program.encode(), 'text/html'
            elif route == '/overlay':
                data, kind = (ROOT/'vendor/overlay/overlay.html').read_bytes(), 'text/html'
            elif route == '/boost-animation.js':
                data, kind = (ROOT/'vendor/overlay/boost-animation.js').read_bytes(), 'application/javascript'
            elif route == '/audio/engine-start.wav':
                data, kind = (ROOT/'vendor/audio/engine-start.wav').read_bytes(), 'audio/wav'
            elif route == '/postmatch':
                data, kind = (ROOT/'vendor/postmatch/postmatch.html').read_bytes(), 'text/html'
            else:
                data, kind = b'', 'text/html'
            self.send_response(200)
            self.send_header('Content-Type', kind+';charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run([
                r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                '--headless', '--autoplay-policy=no-user-gesture-required', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                '--disable-background-networking', '--disable-component-update',
                '--user-data-dir='+profile, '--virtual-time-budget=5000', '--dump-dom',
                f'http://127.0.0.1:{server.server_port}/program'],
                capture_output=True, timeout=40)
            output = result.stdout.decode(errors='replace')
            if 'data-qa="PASS"' not in output:
                import re
                raise AssertionError(re.findall(r'data-(?:qa|error)="[^"]*"', output) or result.stderr.decode(errors='replace')[-1000:])
            print('PASS: real browser 800 ms black transition, marker visibility/alignment, audio decode and statistics palette')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()

