"""Online open-licence image lookup (Openverse first, Wikimedia CC0 fallback). Network failures never block a lesson deck."""
import hashlib,io,json,re,time
from pathlib import Path
from urllib.parse import urlparse
from contextvars import ContextVar
import requests
from PIL import Image
from .store import atomic
from . import speedup

API='https://commons.wikimedia.org/w/api.php'
HEADERS={'User-Agent':'TeachingSlidesLocal/2.0 (local classroom slide authoring)'}
CC0_URL='https://creativecommons.org/publicdomain/zero/1.0/'
OPENVERSE='https://api.openverse.org/v1/images/'
OV_LICENSES='cc0,pdm,by,by-sa'
OV_NAMES={'cc0':'CC0 1.0','pdm':'Public Domain Mark','by':'CC BY','by-sa':'CC BY-SA'}
BAD_WORDS=('nude','naked','sex','gore','blood','corpse','weapon','gun','violence','erotic')
QUERY_NOISE={'a','an','the','of','and','with','illustration','illustrations','photo','photograph','image',
             'images','flat','vector','design','educational','minimalist','background','teal','orange','cream',
             'giant','small','cute','little','large','front','view','closeup'}
QUERY_ALIASES={'panda':['giant panda'],'hippo':['hippopotamus'],'bicycle':['bike'],
               'airplane':['aeroplane'],'sneakers':['shoes'],'sofa':['couch']}
_SEARCH_DEADLINE=ContextVar('image_search_deadline',default=None)

def _timeout(connect,read):
    deadline=_SEARCH_DEADLINE.get()
    if deadline is None:return connect,read
    remaining=deadline-time.monotonic()
    if remaining<=.05:raise requests.Timeout('圖片搜尋時間已達上限')
    return min(connect,remaining*.25),min(read,remaining*.75)

def search_variants(keyword):
    """At most three faithful queries; never fall back to unrelated generic art."""
    original=' '.join(keyword.split())
    tokens=re.findall(r'[A-Za-z]+',original.lower())
    core=[w for w in tokens if w not in QUERY_NOISE]
    values=[original]
    cleaned=' '.join(core)
    if cleaned and cleaned.casefold()!=original.casefold():values.append(cleaned)
    for word in core:
        for replacement in QUERY_ALIASES.get(word,[]):
            if set(replacement.split()).issubset(set(core)):continue
            values.append(' '.join(replacement if w==word else w for w in core))
    return list(dict.fromkeys(v for v in values if v))[:3]

def relevant(candidate,keyword):
    """Conservative metadata relevance, not a claim of visual verification."""
    wanted={w for w in re.findall(r'[a-z]+',keyword.lower()) if w not in QUERY_NOISE}
    shown={w for w in re.findall(r'[a-z]+',(candidate.get('title','')+' '+candidate.get('keywords','')).lower())}
    singular=lambda w:w[:-1] if len(w)>4 and w.endswith('s') else w
    return {singular(w) for w in wanted}.issubset({singular(w) for w in shown}) if wanted else False

def credit_line(credit, max_title=40, max_artist=30):
    """One clean credit line for the slide footer: no empty segments, creator never blank."""
    credit = credit or {}
    if credit.get('generated'):
        return '圖片：本機 AI 生成'
    tag = lambda value: re.sub(r'<[^>]+>', '', str(value or '')).strip()
    title = tag(credit.get('title'))[:max_title]
    artist = tag(credit.get('artist')) or tag(credit.get('attribution'))[:max_artist]
    parts = [title or '圖片', artist[:max_artist] or '作者未標示', tag(credit.get('license')),
             tag(credit.get('source_site')) or 'Wikimedia Commons']
    return '圖片：' + '｜'.join(p for p in parts if p)

def valid_image(path):
    try:
        path=Path(path)
        if not path.is_file() or path.stat().st_size>16_000_000:return False
        with Image.open(path) as image:image.verify()
        return True
    except (OSError,ValueError,Image.DecompressionBombError):return False

def openverse_candidate(item):
    """Accept only kid-safe, freely reusable JPEG/PNG results with full credit data."""
    license_code=(item.get('license') or '').lower()
    if license_code not in OV_NAMES:return None
    if item.get('mature') or item.get('unstable__sensitivity'):return None
    text=' '.join([item.get('title') or '']+[t.get('name','') for t in item.get('tags') or []]).lower()
    if any(w in text for w in BAD_WORDS):return None
    url=item.get('thumbnail') or ''
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='api.openverse.org':return None
    if min(item.get('width') or 0,item.get('height') or 0)<400:return None
    version=item.get('license_version') or ''
    name=OV_NAMES[license_code]+((' '+version) if version and license_code in ('by','by-sa') else '')
    return {'title':item.get('title') or '','url':url,
            'description_url':item.get('foreign_landing_url') or item.get('detail_url',''),
            'license':name,'license_url':item.get('license_url') or '',
            'artist':item.get('creator') or '','provider':item.get('provider') or item.get('source') or '',
            'attribution':item.get('attribution') or '','source_site':'Openverse',
            'keywords':' '.join(t.get('name','') for t in item.get('tags') or [])}

def search_openverse(keyword,session=requests):
    response=session.get(OPENVERSE,params={'q':keyword,'license':OV_LICENSES,'mature':'false',
        'page_size':20,'extension':'jpg,png'},headers=HEADERS,timeout=_timeout(3,10))
    response.raise_for_status()
    for item in response.json().get('results',[]) or []:
        candidate=openverse_candidate(item)
        if candidate and relevant(candidate,keyword):return candidate
    return None

def find_image(keyword,session=requests):
    try:
        found=search_openverse(keyword,session)
        if found:return found
    except (requests.RequestException,ValueError,KeyError,AttributeError):pass
    return search_cc0(keyword,session)

SEARCH_TTL=7*86400

def find_image_cached(keyword,session=requests,root=None):
    """find_image with a seven-day cross-job memory of successful searches (a failure is never remembered)."""
    hit=speedup.get(root,'image-search',keyword,ttl=SEARCH_TTL)
    if hit:return hit
    found=find_image(keyword,session)
    if found:speedup.put(root,'image-search',keyword,found)
    return found

def keyword_for(item):
    """The search words a slide asks for (media hint first, otherwise the start of its image prompt)."""
    visual=item.get('visual_asset')
    keyword=(item.get('media_hint') or {}).get('search_keyword','').strip()
    if not keyword and visual and visual.get('image_prompt'):
        keyword=' '.join(re.sub(r'[^A-Za-z ]',' ',visual['image_prompt']).split()[:5])
    return keyword


def _metadata(value,key):
    return value.get('extmetadata',{}).get(key,{}).get('value','')

def cc0_candidate(page):
    info=(page.get('imageinfo') or [{}])[0]
    license_name=_metadata(info,'LicenseShortName').strip().casefold()
    license_url=_metadata(info,'LicenseUrl').rstrip('/')+'/'
    url=info.get('thumburl') or info.get('url','')
    parsed=urlparse(url)
    if license_name not in ('cc0','cc0 1.0') or license_url!=CC0_URL:return None
    if info.get('mime') not in ('image/jpeg','image/png'):return None
    if parsed.scheme!='https' or parsed.hostname!='upload.wikimedia.org':return None
    return {'title':page.get('title',''),'url':url,
            'description_url':info.get('descriptionurl',''),
            'license':'CC0 1.0','license_url':CC0_URL,
            'artist':_metadata(info,'Artist')}

def search_cc0(keyword,session=requests):
    response=session.get(API,params={'action':'query','generator':'search',
        'gsrsearch':keyword,'gsrnamespace':6,'gsrlimit':15,'prop':'imageinfo',
        'iiprop':'url|mime|extmetadata','iiurlwidth':1200,
        'iiextmetadatafilter':'LicenseShortName|LicenseUrl|Artist',
        'format':'json','formatversion':2},headers=HEADERS,timeout=_timeout(3,8))
    response.raise_for_status()
    for page in response.json().get('query',{}).get('pages',[]):
        candidate=cc0_candidate(page)
        if candidate and relevant(candidate,keyword):return candidate
    return None

def download(candidate,folder,session=requests,max_bytes=8_000_000):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    response=session.get(candidate['url'],headers=HEADERS,timeout=_timeout(3,3),stream=True,
                         allow_redirects=False)
    response.raise_for_status()
    if response.status_code!=200:raise ValueError('圖片網址轉址或回覆異常')
    chunks=[];size=0
    for chunk in response.iter_content(64*1024):
        _timeout(3,3)
        size+=len(chunk)
        if size>max_bytes:raise ValueError('圖片超過大小上限')
        chunks.append(chunk)
    raw=b''.join(chunks)
    with Image.open(io.BytesIO(raw)) as image:
        image.verify()
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('JPEG','PNG','WEBP'):raise ValueError('圖片格式不支援')
        if image.format=='WEBP':
            buffer=io.BytesIO();image.convert('RGB').save(buffer,format='PNG');raw=buffer.getvalue()
            suffix='.png'
        else:suffix='.jpg' if image.format=='JPEG' else '.png'
    target=folder/(hashlib.sha256(raw).hexdigest()+suffix)
    if not target.exists():target.write_bytes(raw)
    return target

def _online_images(deck,out,existing=None,session=requests,max_images=15,failed_keywords=None,search_budget_seconds=25):
    """Search open-licence images for slides that need one; keep credits beside the deck."""
    out=Path(out);media=dict(existing or {});manifest=out/'image-sources.json'
    records=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    downloaded=0;searched={};status={};deadline=time.monotonic()+search_budget_seconds
    failed_keywords=failed_keywords if failed_keywords is not None else set()
    # Look up every wanted picture at the same time (three at once), then walk the pages in order.
    wanted=[]
    for number,item in enumerate(deck['slides'],1):
        if number in media or item['layout_id'] not in ('bullet_with_image','Text_Visual','Cover'):continue
        visual=item.get('visual_asset')
        if visual and not visual['is_required']:continue
        keyword=keyword_for(item)
        if not keyword or keyword in failed_keywords:continue
        old=records.get(str(number))
        if old and old.get('search_keyword')==keyword and not old.get('generated') and valid_image(old.get('local_path','')):continue
        first=search_variants(keyword)[0]
        if first not in failed_keywords and first not in wanted:wanted.append(first)
    prefetched={}
    cache_root=speedup.root_of(out)
    def fetch(query):
        candidate=find_image_cached(query,session,cache_root)
        path=None
        if candidate:
            try:path=download(candidate,out/'images',session)
            except (requests.RequestException,OSError,ValueError,KeyError):pass  # the page loop retries with the other provider
        return candidate,path
    if time.monotonic()<deadline:
        for query,result in zip(wanted[:max_images],speedup.parallel(fetch,wanted[:max_images],workers=3)):
            if isinstance(result,tuple):
                searched[query]=result[0]
                if result[0] and result[1]:prefetched[result[0]['url']]=result[1]
    for number,item in enumerate(deck['slides'],1):
        if number in media or item['layout_id'] not in ('bullet_with_image','Text_Visual','Cover'):continue
        visual=item.get('visual_asset')
        if visual and not visual['is_required']:continue
        keyword=keyword_for(item)
        if not keyword:continue
        old=records.get(str(number))
        if (old and old.get('search_keyword')==keyword
                and not old.get('generated') and valid_image(old.get('local_path',''))):
            media[number]=old['local_path'];downloaded+=1
            if visual and visual.get('is_required'):
                status[str(number)]={'status':'cached','path':old['local_path'],
                                     'teaching_purpose':visual.get('reasoning','')}
            continue
        # Page numbering can change during pagination. Never attach a cached
        # picture for a different query to this page, even if the file exists.
        records.pop(str(number),None)
        if keyword in failed_keywords:
            if visual and visual.get('is_required'):
                status[str(number)]={'status':'unavailable','reason':'本次排版已確認圖片搜尋失敗：'+keyword,
                                     'teaching_purpose':visual.get('reasoning','')}
            continue
        if downloaded>=max_images:
            if visual and visual.get('is_required'):
                status[str(number)]={'status':'skipped','reason':'已達本份簡報配圖上限',
                                     'teaching_purpose':visual.get('reasoning','')}
            continue
        attempts=[];last_error='找不到合適且授權允許的圖片'
        for query in search_variants(keyword):
            if time.monotonic()>=deadline:
                last_error='本份簡報的圖片搜尋時間已達上限';break
            if query in failed_keywords:continue
            attempts.append(query)
            try:
                if query not in searched:searched[query]=find_image_cached(query,session,cache_root)
                candidate=searched[query]
                if not candidate:
                    failed_keywords.add(query);continue
                try:path=prefetched.get(candidate['url']) or download(candidate,out/'images',session)
                except (requests.RequestException,OSError,ValueError,KeyError):
                    if candidate.get('source_site')!='Openverse':raise
                    # A broken first provider URL does not mean the subject
                    # cannot be illustrated. Try the other licensed provider.
                    candidate=search_cc0(query,session)
                    if not candidate:raise ValueError('第一個圖庫下載失敗，第二個圖庫無合適素材')
                    path=download(candidate,out/'images',session)
                media[number]=str(path);records[str(number)]={**candidate,'local_path':str(path),
                    'search_keyword':keyword,'resolved_query':query,'search_attempts':attempts}
                downloaded+=1
                if visual and visual.get('is_required'):status[str(number)]={'status':'cached','path':str(path),
                    'teaching_purpose':visual.get('reasoning',''),'search_attempts':attempts}
                break
            except (requests.RequestException,OSError,ValueError,KeyError) as exc:
                failed_keywords.add(query);last_error='圖片搜尋或下載失敗：'+str(exc)[:160]
        if number not in media:
            failed_keywords.add(keyword)
            if visual and visual.get('is_required'):status[str(number)]={'status':'unavailable',
                'reason':last_error+'：'+keyword,'search_attempts':attempts,'teaching_purpose':visual.get('reasoning','')}
    atomic(manifest,records)
    if status:
        va=out/'visual-assets.json'
        prior=json.loads(va.read_text(encoding='utf-8')) if va.exists() else {}
        prior.update(status);atomic(va,prior)
    return media

def online_images(deck,out,existing=None,session=requests,max_images=15,failed_keywords=None,search_budget_seconds=25):
    token=_SEARCH_DEADLINE.set(time.monotonic()+max(0,search_budget_seconds))
    try:return _online_images(deck,out,existing,session,max_images,failed_keywords,search_budget_seconds)
    finally:_SEARCH_DEADLINE.reset(token)
