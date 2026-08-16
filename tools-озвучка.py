import torch, numpy as np, wave, json, re, os, sys, subprocess
torch.set_num_threads(4)
SR=48000
SPK=sys.argv[1] if len(sys.argv)>1 else 'xenia'
OUT='audio'
model,_=torch.hub.load('snakers4/silero-models','silero_tts',language='ru',speaker='v4_ru',trust_repo=True)
def gen(t):
    return model.apply_tts(text=t,speaker=SPK,sample_rate=SR,put_accent=True,put_yo=True).numpy()
def trim(a,rel=0.06):
    e=np.abs(a); i=np.where(e>e.max()*rel)[0]
    return a[max(0,i[0]-int(.01*SR)):min(len(a),i[-1]+int(.02*SR))]
def period(x):
    x=x-x.mean(); n=len(x); ac=np.correlate(x,x,'full')[n-1:]
    lo,hi=int(SR/400),int(SR/70); return lo+int(np.argmax(ac[lo:hi]))
def sustain(a,seconds,at=None):
    a=trim(a); m=at if at else len(a)//2
    P=period(a[max(0,m-2048):m+2048]); K=max(1,int(0.12*SR//P))
    st=max(0,m-K*P//2); chunk=a[st:st+K*P]
    if len(chunk)<P*2: return a
    xf=P; out=list(a[:st]); body=[]
    while (len(out)+len(body))/SR < seconds-0.2:
        if not body: body=list(chunk)
        else:
            f=np.linspace(0,1,xf); tail=np.array(body[-xf:])
            body[-xf:]=list(tail*(1-f)+chunk[:xf]*f); body+=list(chunk[xf:])
    out=np.array(out+body+list(a[st+K*P:]))
    r=int(.12*SR); out[-r:]*=np.linspace(1,0,r)
    return out*(1+0.03*np.sin(2*np.pi*4.5*np.arange(len(out))/SR))
TR={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y',
    'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f',
    'х':'h','ц':'c','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}
def slug(s):
    s=s.lower(); o=''.join(TR.get(c,c if c.isalnum() else '-') for c in s)
    return re.sub(r'-+','-',o).strip('-')[:40] or 'x'
def save_mp3(path,a):
    x=(np.clip(a/max(1e-9,np.abs(a).max())*0.92,-1,1)*32767).astype('<i2')
    w='/tmp/_g.wav'
    with wave.open(w,'wb') as f: f.setnchannels(1);f.setsampwidth(2);f.setframerate(SR);f.writeframes(x.tobytes())
    subprocess.run(['ffmpeg','-y','-v','error','-i',w,'-ar','24000','-ac','1','-b:a','48k',path],check=True)

HOLD={"а-а-а-а":"а","у-у-у-у":"у","и-и-и-и":"и"}
PHRASES=(["а-а-а-а","у-у-у-у","и-и-и-и","А","О","У","И","Э","Ы",
 "ВА","ВО","ВУ","ВЫ","АВА","ОВО","УВУ","ЫВЫ",
 "ВОДА","ВЕТЕР","ВОЛК","ВИЛКА","ВАННА","ВЕРТОЛЁТ","КОРОВА","СОВА",
 "Ва-ва-ва, вот высокая трава",
 "Ты постарался!","У тебя получается!","Вот это да!","Ты справился!",
 "Как здорово вышло!","С каждым разом всё лучше!","Ты не сдался — и вышло!",
 "Я горжусь тобой!","Молодец, что попробовал!","Хорошо поработал!",
 "Смотри, как ты можешь!","Ты сегодня хорошо старался!",
 "Вот так!","Получилось!","Хорошо!","Молодец!","Здорово!","Так держать!","Уже лучше!","Ты смог!",
 "Ты сделал всё!","Ничего, слушай ещё разок"]
 + json.load(open('/tmp/_stickers.json')))
os.makedirs(OUT,exist_ok=True)
man={}
for p in PHRASES:
    k=p.strip().lower()
    if k in man: continue
    fn=OUT+'/'+slug(k)+'.mp3'
    a = sustain(gen(HOLD[k]),4.0) if k in HOLD else trim(gen(p))
    save_mp3(fn,a); man[k]=fn
json.dump(man,open('/tmp/_manifest.json','w'),ensure_ascii=False,indent=0)
print("готово файлов:",len(man))
