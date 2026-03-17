"""
Gerenciador de sessão persistente do navegador para o SAGGESTAO.

Mantém o navegador Playwright aberto entre operações, evitando o custo
de abrir/fechar browser para cada bloqueio/desbloqueio. Gerencia o
keep-alive da sessão e recuperação automática em caso de falha.
"""

import time
import logging
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from config import (
    SESSION_KEEPALIVE_INTERVAL, 
    BROWSER_HEADLESS,
    SAGGESTAO_CONSULTATION_URL,
    PLAYWRIGHT_DEFAULT_TIMEOUT
)
from auth import SaggestaoAuth

logger = logging.getLogger("RPA.SessionManager")

# Seletor do input SIAPE, usado para verificar se a página carregou corretamente
SIAPE_FIELD_SELECTOR = 'input[name="form\\:idMskSiape"]'


class SaggestaoSessionManager:
    """
    Gerencia o ciclo de vida do navegador Playwright e da sessão SAGGESTAO.

    Responsabilidades:
    - Manter browser aberto e sessão ativa entre operações
    - Executar keep-alive não intrusivo para evitar timeout
    - Detectar queda de sessão e recuperar automaticamente
    - Encerrar recursos de forma limpa no shutdown
    """

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_activity_time = 0.0
        self._active = False

    # ============================================
    # Ciclo de Vida
    # ============================================

    def start(self):
        """Inicia o Playwright e estabelece sessão inicial com o SAGGESTAO."""
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
        """Lança browser, obtém contexto autenticado e navega para consulta."""
        try:
            # Lança browser se não existe ou desconectou
            if self._browser is None or not self._browser.is_connected():
                logger.info(f"Iniciando navegador Chromium (headless={BROWSER_HEADLESS})...")
                self._browser = self._playwright.chromium.launch(headless=BROWSER_HEADLESS)

            # Fecha context antigo se existir
            if self._context:
                try:
                    self._context.close()
                except Exception:
                    pass

            # Cria novo contexto AUTENTICADO via auth.py
            logger.info("Configurando contexto autenticado...")
            self._context = SaggestaoAuth.configurar_contexto(self._browser)

            # Cria page e navega
            self._page = self._context.new_page()
            self._page.set_default_timeout(PLAYWRIGHT_DEFAULT_TIMEOUT)
            self._page.set_viewport_size({"width": 1024, "height": 768})

            self._navigate_to_consultation()
            self._last_activity_time = time.time()

        except Exception as e:
            logger.error(f"Falha ao estabelecer sessão: {e}")
            raise

    # ============================================
    # Navegação
    # ============================================

    def _navigate_to_consultation(self):
        """Navega para a página de consulta, tratando seleção de domínio."""
        logger.info(f"Navegando para URL de consulta: {SAGGESTAO_CONSULTATION_URL}")
        try:
            self._page.goto(SAGGESTAO_CONSULTATION_URL, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT)
            logger.info("Navegação inicial concluída.")
        except Exception as e:
            logger.warning(f"Aviso durante navegação inicial: {e}")

        # Trata seleção de domínio (se aparecer)
        try:
            if self._page.locator("select#domains").is_visible(timeout=5000):
                logger.info("Página de seleção de domínio DETECTADA. Selecionando UO:01.001.PRES...")
                self._page.select_option("select#domains", "UO:01.001.PRES")
                logger.info("Clicando no botão 'Enviar'...")
                self._page.get_by_role("button", name="Enviar").click()
                self._page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
                logger.info("Seleção de domínio concluída.")
            else:
                logger.debug("Página de seleção de domínio NÃO detectada.")
        except Exception as e:
            logger.debug(f"Exceção não-crítica ao verificar seleção de domínio: {e}")

        # Força navegação se não caiu na página de consulta
        if "consultar.xhtml" not in self._page.url:
            logger.warning(f"Redirecionado para: {self._page.url}. Forçando navegação para consulta...")
            try:
                self._page.goto(SAGGESTAO_CONSULTATION_URL, timeout=30000)
            except Exception as e:
                logger.error(f"Erro ao forçar navegação: {e}")

        # Verifica carregamento
        try:
            self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=30000)
            logger.info("Página de consulta carregada com SUCESSO.")
        except Exception:
            logger.error(f"Falha ao carregar página de consulta. URL: {self._page.url}")
            raise Exception("Página de consulta não carregou corretamente.")

    def navigate_to_consultation(self):
        """Navega de volta para a página de consulta após uma operação."""
        try:
            # Só navega se já não estiver lá
            if "consultar.xhtml" not in self._page.url:
                self._page.goto(SAGGESTAO_CONSULTATION_URL, timeout=30000)
            
            self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=15000)
            logger.debug("Navegou de volta para página de consulta.")
        except Exception as e:
            logger.warning(f"Falha ao navegar para consulta: {e}")

    # ============================================
    # Ponto de Entrada Principal
    # ============================================

    def ensure_ready(self) -> Page:
        """
        Garante que a sessão está pronta para uso. Retorna o Page.
        Detecta sessão inválida e recupera automaticamente.
        """
        if not self._active or self._page is None:
            logger.info("Sessão não ativa. Estabelecendo nova sessão...")
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            self._establish_session()
            self._active = True
            return self._page

        # Health check
        if not self._is_session_healthy():
            logger.warning("Sessão inválida detectada. Tentando recuperar...")
            self._recover_session()
            return self._page

        # Keep-alive se ocioso por muito tempo
        elapsed = time.time() - self._last_activity_time
        if elapsed >= SESSION_KEEPALIVE_INTERVAL:
            logger.info(f"Sessão ociosa por {elapsed:.0f}s. Executando keep-alive...")
            self._perform_keepalive()

        return self._page

    def mark_activity(self):
        """Registra que uma operação real foi executada (reseta timer de keep-alive)."""
        self._last_activity_time = time.time()

    # ============================================
    # Detecção de Saúde e Recuperação
    # ============================================

    def _is_session_healthy(self) -> bool:
        """
        Verifica se a sessão do browser ainda é válida.
        """
        try:
            if self._browser is None or not self._browser.is_connected():
                logger.warning("Health check: Browser desconectado.")
                return False

            if self._page is None or self._page.is_closed():
                logger.warning("Health check: Page fechada.")
                return False

            current_url = self._page.url
            # Se não está em consulta/alteração, pode ter sido redirecionado para login
            if "consultar.xhtml" not in current_url and "alterar.xhtml" not in current_url:
                logger.warning(f"Health check: URL inesperada: {current_url}")
                return False

            # Verificação rápida do campo SIAPE (apenas na página de consulta)
            if "consultar.xhtml" in current_url:
                try:
                    state = self._page.locator(SIAPE_FIELD_SELECTOR).is_visible(timeout=5000)
                    if not state:
                        logger.warning("Health check: Campo SIAPE não visível.")
                        return False
                except Exception:
                    logger.warning("Health check: Exceção ao verificar campo SIAPE.")
                    return False

            return True

        except Exception as e:
            logger.warning(f"Health check falhou com exceção: {e}")
            return False

    def _recover_session(self):
        """Recupera sessão: fecha context antigo e re-autentica."""
        logger.info("Iniciando recuperação de sessão...")

        # Fecha context/page antigos
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

        # Re-estabelece sessão
        try:
            self._establish_session()
            logger.info("Sessão recuperada com SUCESSO.")
        except Exception as e:
            logger.error(f"Falha crítica na recuperação de sessão: {e}")
            raise

    # ============================================
    # Keep-Alive Otimizado
    # ============================================

    def _perform_keepalive(self):
        """
        Mantém a sessão ativa recarregando a página de consulta.
        Isso renova o tempo de expiração no servidor sem disparar buscas fictícias.
        """
        try:
            logger.debug("Executando keep-alive (reload)...")
            self._page.reload(timeout=PLAYWRIGHT_DEFAULT_TIMEOUT)
            self._page.wait_for_selector(SIAPE_FIELD_SELECTOR, timeout=15000)
            self._last_activity_time = time.time()
            logger.info("Keep-alive executado com SUCESSO.")
        except Exception as e:
            logger.warning(f"Keep-alive falhou: {e}. Sessão pode ter expirado.")
