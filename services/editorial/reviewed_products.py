"""Manufacturer references inspected on 2026-10-23; never inferred CDN paths.

These are a reusable research cache, not a source of store prices/availability.
The owner's Bay Blue confirmation disambiguates the colloquial 'bleu ciel'.
"""
import re
import unicodedata

def normalized(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value)).encode('ascii','ignore').decode().lower())

HAILUN_SOURCE='https://www.hailunpiano.com/index.php?a=show&c=index&catid=138&id=362&m=content'
HAILUN_REFERENCES=(
    ('Warm Sun Orange',('warm sun orange','orange chaud','orange'), 'https://img.pinweixin.com.cn/hailun/20251112/HD-300-3.jpg'),
    ('Bay Blue',('bay blue','bleu baie'), 'https://img.pinweixin.com.cn/hailun/20251112/HD-300-7.jpg'),
    ('Deep Sea Blue',('deep sea blue','bleu mer profond','bleu nuit'), 'https://img.pinweixin.com.cn/hailun/20251112/HD-300-2.jpg'),
)

def reviewed_references(identity,variants,query):
    name=normalized(' '.join(str(identity.get(k,'')) for k in ('brand','model','title')))
    if not ('hailun' in name or 'pianova' in name) or not re.search(r'hd300(?![0-9])',name):return []
    if not 1<=len(variants)<=3:return []
    result=[]
    for variant in variants:
        names={normalized(variant.get(k,'')) for k in ('requested_name','manufacturer_name')}
        # Sky blue has two plausible manufacturer variants; require the user's clarification.
        if 'bleuciel' in names and not any(alias in normalized(query) for alias in ('bleubaie','bayblue')):return []
        matches=[(label,url) for label,aliases,url in HAILUN_REFERENCES if names.intersection(map(normalized,aliases))]
        if len(matches)!=1:return []
        label,url=matches[0]
        if any(r['url']==url for r in result):return []
        result.append({'url':url,'label':label,'source_url':HAILUN_SOURCE,'verified_on':'2026-10-23'})
    return result
