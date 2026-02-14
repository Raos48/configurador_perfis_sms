import requests
import urllib3
import json
from colorama import Fore, Style, init
import time
from datetime import datetime

headers={'Comando':'NovaSessao', 'Sistema':'SAGGESTAO'}
s = requests.Session()
r = s.get("http://localhost:48000", verify=False,headers=headers,timeout=10000)
print(r.text)