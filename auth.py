"""
Módulo de Autenticação e Gestão de Sessão do SAGGESTAO.

Centraliza a lógica de obtenção de JSESSIONID e configuração de contexto do Playwright.
Utiliza tenacity para retries robustos.
"""

import logging
import requests
import urllib3
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from playwright.sync_api import Browser, BrowserContext

from config import (
    SAGGESTAO_CONSULTATION_URL,
    MAX_RETRIES,
    LOG_LEVEL
)

# Configuração de Logger
logger = logging.getLogger("RPA.Auth")
logger.setLevel(LOG_LEVEL)

# Desativa avisos de SSL (apenas neste módulo, se necessário)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SaggestaoAuth:
    """
    Gerencia a autenticação no SAGGESTAO via injeção de cookie JSESSIONID.
    """

    LOCAL_AUTH_URL = "http://localhost:48000"

    @staticmethod
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True
    )
    def obter_jsessionid() -> str:
        """
        Obtém o JSESSIONID do servidor de autenticação local.
        
        Returns:
            str: O valor do JSESSIONID.
        
        Raises:
            requests.RequestException: Se houver erro de conexão ou timeout após retries.
            ValueError: Se a resposta não contiver JSESSIONID válido.
        """
        logger.info("Obtendo JSESSIONID de %s...", SaggestaoAuth.LOCAL_AUTH_URL)
        headers = {'Comando': 'NovaSessao', 'Sistema': 'SAGGESTAO'}
        
        try:
            response = requests.get(
                SaggestaoAuth.LOCAL_AUTH_URL, 
                headers=headers, 
                verify=False, 
                timeout=120
            )
            response.raise_for_status()
            
            data = response.json()
            jsessionid = data.get('JSESSIONID')
            
            if not jsessionid:
                raise ValueError("Resposta do servidor não contém JSESSIONID.")
                
            logger.info("JSESSIONID obtido com sucesso.")
            return jsessionid
            
        except requests.RequestException as e:
            logger.warning(f"Erro na conexão com servidor de autenticação: {e}")
            raise

    @staticmethod
    def configurar_contexto(browser: Browser) -> BrowserContext:
        """
        Cria um novo contexto no browser e injeta o cookie de sessão.

        Args:
            browser (Browser): Instância do browser Playwright.

        Returns:
            BrowserContext: Contexto configurado e autenticado.
        """
        jsessionid = SaggestaoAuth.obter_jsessionid()
        
        context = browser.new_context(ignore_https_errors=True)
        
        # O domínio do cookie deve corresponder ao host do SAGGESTAO (psagapr01)
        # Extraindo host da URL de consulta para ser mais dinâmico
        from urllib.parse import urlparse
        parsed_url = urlparse(SAGGESTAO_CONSULTATION_URL)
        domain = parsed_url.hostname or "psagapr01"

        logger.info(f"Injetando cookie JSESSIONID para domínio: {domain}")
        context.add_cookies([{
            "name": "JSESSIONID",
            "value": jsessionid,
            "url": f"{parsed_url.scheme}://{domain}"
        }])
        
        return context
