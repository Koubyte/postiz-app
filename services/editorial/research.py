"""Extract real image links from a verified public product page, without guessing URLs."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

class ProductImages(HTMLParser):
    def __init__(self,url):
        super().__init__(convert_charrefs=True)
        self.url=url;self.images=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        values=[]
        if tag=='img':
            for key in ('src','data-src','data-original'):
                if attrs.get(key):values.append(attrs[key])
            if attrs.get('srcset'):
                values.extend(p.strip().split()[0] for p in attrs['srcset'].split(',') if p.strip())
        elif tag=='meta' and (attrs.get('property') or attrs.get('name')) in ('og:image','twitter:image'):
            values.append(attrs.get('content',''))
        for value in values:
            url=urljoin(self.url,value)
            if urlsplit(url).scheme!='https' or not urlsplit(url).hostname:continue
            if urlsplit(url).path.lower().endswith(('.svg','.gif')):continue
            if any(i['url']==url for i in self.images):continue
            if len(self.images)<40:self.images.append({'url':url,'alt':attrs.get('alt',attrs.get('title',''))[:200]})

def product_images(html,url):
    parser=ProductImages(url);parser.feed(html)
    return parser.images
