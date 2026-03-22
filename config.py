"""
Configurações do Serviço RPA de Bloqueio de Perfis.
Centraliza todas as configurações necessárias para comunicação com a API SIGA
e controle do loop de polling.
"""

import os
import warnings
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env (se existir)
load_dotenv()

# ============================================
# Configurações da API SIGA
# ============================================
# Ambiente ativo: "local" usa SIGA_API_URL, "cloud" usa SIGA_API_URL_CLOUD
# Para alternar, edite API_ENV no arquivo .env e reinicie o serviço.
_API_ENV = os.environ.get("API_ENV", "local").lower()
_SIGA_API_URL_LOCAL = os.environ.get("SIGA_API_URL", "http://localhost:8000")
_SIGA_API_URL_CLOUD = os.environ.get(
    "SIGA_API_URL_CLOUD",
    "https://sgben-sigabackend.bpbeee.easypanel.host"
)

API_ENV = _API_ENV
SIGA_API_URL = _SIGA_API_URL_CLOUD if _API_ENV == "cloud" else _SIGA_API_URL_LOCAL

# Credenciais da conta staff usada pelo RPA
# IMPORTANTE: A conta precisa ter is_staff=True no Django
SIGA_EMAIL = os.environ.get("SIGA_EMAIL")
SIGA_PASSWORD = os.environ.get("SIGA_PASSWORD")

# Aviso em vez de erro — scripts standalone não precisam das credenciais de API
if not SIGA_EMAIL or not SIGA_PASSWORD:
    warnings.warn(
        "SIGA_EMAIL/SIGA_PASSWORD não configurados. "
        "Funcionalidades de API SIGA não estarão disponíveis.",
        stacklevel=1,
    )

# URL direta para a página de consulta do SAGGESTAO
SAGGESTAO_CONSULTATION_URL = os.environ.get(
    "SAGGESTAO_CONSULTATION_URL",
    "http://psagapr01/saggestaoagu/pages/cadastro/profissional/consultar.xhtml"
)

# ============================================
# Configurações de Polling
# ============================================
# Intervalo em segundos entre ciclos quando há itens processados
POLLING_INTERVAL = int(os.environ.get("POLLING_INTERVAL", "5"))

# Intervalo em segundos quando não há pedidos pendentes
POLLING_INTERVAL_IDLE = int(os.environ.get("POLLING_INTERVAL_IDLE", "10"))

# ============================================
# Configurações de Sessão do SAGGESTAO
# ============================================
# Intervalo em segundos para keep-alive da sessão do SAGGESTAO (padrão: 240s = 4min)
SESSION_KEEPALIVE_INTERVAL = int(os.environ.get("SESSION_KEEPALIVE_INTERVAL", "240"))

# Executar navegador em modo headless (sem janela visível)
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "false"

# Timeout padrão para operações do Playwright (em milissegundos)
PLAYWRIGHT_DEFAULT_TIMEOUT = int(os.environ.get("PLAYWRIGHT_DEFAULT_TIMEOUT", "60000"))

# Número máximo de retries para operações críticas
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "4"))

# ============================================
# Configurações de Log
# ============================================
LOG_FILE = os.environ.get("LOG_FILE", "rpa_bloqueios.log")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
