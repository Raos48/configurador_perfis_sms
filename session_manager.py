"""
Gerenciador de sessão persistente do navegador para o SAGGESTAO.

Mantém o navegador Playwright aberto entre operações, evitando o custo
de abrir/fechar browser para cada bloqueio/desbloqueio. Gerencia o
keep-alive da sessão e recuperação automática em caso de falha.
"""

import time
import logging
import requests
import urllib3
from playwright.sync_api import sync_playwright, Page

from config import SESSION_KEEPALIVE_INTERVAL, BROWSER_HEADLESS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("RPA.SessionManager")

CONSULTATION_URL = "http://psagapr01/saggestaoagu/pages/cadastro/profissional/consultar.xhtml"
SIAPE_FIELD_SELECTOR = 'input[name="form\\:idMskSiape"]'


class SaggestaoSessionManager:
    """
    Gerencia o ciclo de vida do navegador Playwright e da sessão SAGGESTAO.

    Responsabilidades:
    - Manter browser aberto e sessão ativa entre operações
    - Executar keep-alive periódico (busca fictícia) para evitar timeout
    - Detectar queda de sessão e recuperar automaticamente
    - Encerrar recursos de forma limpa no shutdown
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._last_activity_time = 0.0
        self._active = False

    # ============================================
    # Ciclo de Vida
    # ============================================

    def start(self):
        """Inicia o Playwright e estabelece sessao inicial com o SAGGESTAO."""
        logger.info("Iniciando SessionManager...")
        self._playwright = sync_playwright().start()
        self._establish_session()
        self._active = True
        logger.info("SessionManager iniciado com sucesso.")

    def shutdown(self):
        """Encerramento graceful: fecha page, context, browser, playwright."""
        logger.info("Encerrando SessionManager...")
        self._active = False

        for resource, name in [
            (self._page, "Page"),
            (self._context, "Context"),
            (self._browser, "Browser"),
        ]:
            try:
                if resource:
                    resource.close()
            except Exception:
                logger.debug(f"Erro ao fechar {name} (ignorado).")

        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            logger.debug("Erro ao parar Playwright (ignorado).")

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("SessionManager encerrado.")

    def _establish_session(self):
        """Obtem JSESSIONID, lanca browser, injeta cookie, navega para consulta."""
        jsessionid = self._obter_jsessionid()
        if not jsessionid:
            raise Exception("Falha ao obter JSESSIONID do servidor local.")

        # Lanca browser se nao existe ou desconectou
        if self._browser is None or not self._browser.is_connected():
            logger.info(f"Iniciando navegador Chromium (headless={BROWSER_HEADLESS})...")
            self._browser = self._playwright.chromium.launch(headless=BROWSER_HEADLESS)

        # Fecha context antigo se existir
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass

        # Cria novo context com cookie
        logger.info("Injetando cookie JSESSIONID...")
        self._context = self._browser.new_context(ignore_https_errors=True)
        self._context.add_cookies([{
            "name": "JSESSIONID",
            "value": jsessionid,
            "url": "http://psagapr01"
        }])

        # Cria page e navega
        self._page = self._context.new_page()
        self._page.set_default_timeout(60000)
        self._page.set_viewport_size({"width": 1024, "height": 768})

        self._navigate_to_consultation()
        self._last_activity_time = time.time()

    # ============================================
    # Obter JSESSIONID
    # ============================================

    def _obter_jsessionid(self):
        """Obtem JSESSIONID do servidor local (localhost:48000). Tenta ate 4 vezes."""
        logger.info("Iniciando obtencao de JSESSIONID...")
        url = "http://localhost:48000"
        headers = {'Comando': 'NovaSessao', 'Sistema': 'SAGGESTAO'}
        max_retries = 4

        for attempt in range(1, max_retries + 1):
            logger.info(f"Tentativa {attempt}/{max_retries} obtendo sessao de {url}...")
            try:
                response = requests.get(url, headers=headers, verify=False, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    jsessionid = data.get('JSESSIONID')
                    if jsessionid:
                        logger.info(f"JSESSIONID obtido com sucesso: {jsessionid[:10]}...")
                        return jsessionid
                else:
                    logger.warning(f"Resposta invalida na tentativa {attempt}: Status {response.status_code}")
            except Exception as e:
                logger.error(f"Erro na tentativa {attempt}: {e}")

            if attempt < max_retries:
                logger.info("Aguardando 2 segundos antes da proxima tentativa...")
                time.sleep(2)

        logger.critical("Falha ao obter JSESSIONID apos todas as tentativas.")
        return None

    # ============================================
    # Navegacao
    # ============================================

    def _navigate_to_consultation(self):
        """Navega para a pagina de consulta, tratando selecao de dominio."""
        logger.info(f"Navegando para URL de consulta: {CONSULTATION_URL}")
        try:
            self._page.goto(CONSULTATION_URL, timeout=120000)
            logger.info("Navegacao inicial concluida.")
        except Exception as e:
            logger.warning(f"Aviso durante navegacao: {e}")

        # Trata selecao de dominio
        try:
            if self._page.locator("select#domains").is_visible(timeout=5000):
                logger.info("Pagina de selecao de dominio DETECTADA. Selecionando UO:01.001.PRES...")
                self._page.select_option("select#domains", "UO:01.001.PRES")
                logger.info("Clicando no botao 'Enviar'...")
                self._page.get_by_role("button", name="Enviar").click()
                self._page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
                logger.info("Selecao de dominio concluida.")
            else:
                logger.info("Pagina de selecao de dominio NAO detectada. Seguindo fluxo normal.")
        except Exception as e:
            logger.debug(f"Excecao nao-critica ao verificar selecao de dominio: {e}")

        # Forca navegacao se nao esta na pagina de consulta
        if "consultar.xhtml" not in self._page.url:
            logger.warning(f"Redirecionado para: {self._page.url}. Forcando navegacao para consulta...")
            try:
                self._page.goto(CONSULTATION_URL, timeout=60000)
                logger.info("Navegacao forcada concluida.")
            except Exception as e:
                logger.error(f"Erro ao forcar navegacao: {e}")

        # Verifica se carregou
        try:
            self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=30000)
            logger.info("Pagina de consulta carregada com SUCESSO.")
        except Exception:
            logger.error(f"Falha ao carregar pagina de consulta. URL: {self._page.url}")
            raise Exception("Pagina de consulta nao carregou corretamente.")

    def navigate_to_consultation(self):
        """Navega de volta para a pagina de consulta apos uma operacao."""
        try:
            self._page.goto(CONSULTATION_URL, timeout=30000)
            self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=15000)
            logger.debug("Navegou de volta para pagina de consulta.")
        except Exception as e:
            logger.warning(f"Falha ao navegar para consulta: {e}")

    # ============================================
    # Ponto de Entrada Principal
    # ============================================

    def ensure_ready(self) -> Page:
        """
        Garante que a sessao esta pronta para uso. Retorna o Page.
        Detecta sessao invalida e recupera automaticamente.
        """
        if not self._active or self._page is None:
            logger.info("Sessao nao ativa. Estabelecendo nova sessao...")
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            self._establish_session()
            self._active = True
            return self._page

        # Health check
        if not self._is_session_healthy():
            logger.warning("Sessao invalida detectada. Recuperando...")
            self._recover_session()
            return self._page

        # Keep-alive se ocioso por muito tempo
        elapsed = time.time() - self._last_activity_time
        if elapsed >= SESSION_KEEPALIVE_INTERVAL:
            logger.info(f"Sessao ociosa por {elapsed:.0f}s. Executando keep-alive...")
            self._perform_keepalive()

        return self._page

    def mark_activity(self):
        """Registra que uma operacao real foi executada (reseta timer de keep-alive)."""
        self._last_activity_time = time.time()

    # ============================================
    # Deteccao de Saude e Recuperacao
    # ============================================

    def _is_session_healthy(self) -> bool:
        """
        Verifica se a sessao do browser ainda e valida.

        Checagens:
        1. Browser conectado
        2. Page nao fechada
        3. URL correta (nao redirecionado para login)
        4. Campo SIAPE presente (sessao nao expirou)
        """
        try:
            if self._browser is None or not self._browser.is_connected():
                logger.warning("Health check: Browser desconectado.")
                return False

            if self._page is None or self._page.is_closed():
                logger.warning("Health check: Page fechada.")
                return False

            current_url = self._page.url
            if "consultar.xhtml" not in current_url and "alterar.xhtml" not in current_url:
                logger.warning(f"Health check: URL inesperada: {current_url}")
                return False

            # Verificacao rapida do campo SIAPE (apenas na pagina de consulta)
            if "consultar.xhtml" in current_url:
                try:
                    self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=5000)
                except Exception:
                    logger.warning("Health check: Campo SIAPE nao encontrado.")
                    return False

            return True

        except Exception as e:
            logger.warning(f"Health check falhou com excecao: {e}")
            return False

    def _recover_session(self):
        """Recupera sessao: fecha context antigo, obtem novo JSESSIONID, re-navega."""
        logger.info("Iniciando recuperacao de sessao...")

        # Fecha context/page antigos (browser fica aberto se possivel)
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        self._page = None
        self._context = None

        # Se browser desconectou, fecha e limpa
        if self._browser and not self._browser.is_connected():
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        # Re-estabelece sessao
        self._establish_session()
        logger.info("Sessao recuperada com SUCESSO.")

    # ============================================
    # Keep-Alive
    # ============================================

    def _perform_keepalive(self):
        """
        Mantem a sessao ativa executando uma busca ficticia na pagina de consulta.
        Preenche SIAPE "0000000", pesquisa, e volta a pagina limpa.
        """
        try:
            # Garante que esta na pagina de consulta
            if "consultar.xhtml" not in self._page.url:
                self._page.goto(CONSULTATION_URL, timeout=30000)
                self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=15000)

            # Busca ficticia
            self._page.fill(SIAPE_FIELD_SELECTOR, "0000000")
            self._page.click('role=button[name="Pesquisar"]')
            time.sleep(2)

            # Volta a pagina limpa
            self._page.goto(CONSULTATION_URL, timeout=30000)
            self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=15000)

            self._last_activity_time = time.time()
            logger.info("Keep-alive executado com SUCESSO.")

        except Exception as e:
            logger.warning(f"Keep-alive falhou: {e}. Sessao pode ter expirado.")
