"""
Módulo de automação do SAGGESTAO para bloqueio/desbloqueio de perfis.

Contém a lógica de browser automation (Playwright) para interagir com o
sistema legado SAGGESTAO. Pode ser usado como módulo importado pelo
servico_rpa.py ou executado diretamente via CLI para testes.
"""

import time
import re
import logging
import sys
import urllib3
from playwright.sync_api import sync_playwright, Page, BrowserContext

from config import (
    BROWSER_HEADLESS,
    SAGGESTAO_CONSULTATION_URL,
    PLAYWRIGHT_DEFAULT_TIMEOUT,
    MAX_RETRIES
)
from auth import SaggestaoAuth

# --- CONFIGURAÇÃO DE LOG (se executado diretamente) ---
if __name__ == "__main__":
    from colored_logger import setup_colored_logging
    setup_colored_logging(log_level=logging.INFO)

logger = logging.getLogger("BloqueadorPerfis")

# Desativa avisos de SSL se necessário (agora centralizado no auth, mas mantido aqui para compatibilidade)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def buscar_servidor(page: Page, siape: str) -> bool:
    """
    Busca o servidor pelo SIAPE e clica em alterar.
    Inclui retries e fallback JS para o botão de alterar.
    """
    logger.info(f"Iniciando busca pelo servidor com SIAPE: {siape}")
    try:
        # Garante que está na página de consulta
        if "consultar.xhtml" not in page.url:
            logger.warning(f"URL incorreta ({page.url}). Navegando para consulta...")
            page.goto(SAGGESTAO_CONSULTATION_URL, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT)
            page.wait_for_selector('input[name="form\\:idMskSiape"]', timeout=30000)

        page.fill('input[name="form\\:idMskSiape"]', siape)
        logger.info("Campo SIAPE preenchido.")

        logger.info("Clicando em 'Pesquisar'...")
        page.click('role=button[name="Pesquisar"]')

        # Aguarda resposta da pesquisa (load state ou mensagem de erro)
        try:
            with page.expect_response(lambda r: r.url.endswith("consultar.xhtml") and r.status == 200, timeout=10000):
                pass
        except Exception:
            # Se não detectar response, espera um pouco e segue
            time.sleep(2)

        # Verifica se encontrou (mensagem de erro)
        if page.locator("text=Nao foram encontrados registros").or_(page.locator("text=Não foram encontrados registros")).first.is_visible(timeout=3000):
            logger.warning(f"Servidor com SIAPE {siape} NÃO encontrado.")
            return False

        # Clica em Alterar com retries e fallback JS
        logger.info("Registro encontrado. Procurando botão de Alterar...")
        return _clicar_alterar_com_retry(page)

    except Exception as e:
        logger.error(f"Erro durante a busca do servidor: {e}")
        return False


def _clicar_alterar_com_retry(page: Page) -> bool:
    """Tenta clicar no botão de alterar com múltiplas estratégias."""
    seletores = [
        '[id$="idAlterarCadastroProfissional"]',
        'a:has(span.ico-pencil)',
        'a.btn:has(.ico-pencil)',
    ]

    for tentativa in range(1, 4):
        logger.info(f"Tentativa {tentativa}/3 para clicar no botão Alterar...")

        for sel in seletores:
            try:
                btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    logger.info(f"Botão encontrado via seletor: {sel}")
                    btn.first.click()
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    logger.info("Página de edição carregada.")
                    return True
            except Exception as e:
                logger.debug(f"Seletor '{sel}' falhou: {e}")

        # Fallback via JavaScript
        logger.info("Tentando clicar via JavaScript (fallback)...")
        try:
            clicked = page.evaluate("""
                (() => {
                    const links = document.querySelectorAll('a[id*="idAlterarCadastroProfissional"]');
                    if (links.length > 0) { links[0].click(); return true; }
                    const pencils = document.querySelectorAll('.ico-pencil');
                    for (const el of pencils) {
                        const anchor = el.closest('a');
                        if (anchor) { anchor.click(); return true; }
                    }
                    return false;
                })()
            """)
            if clicked:
                logger.info("Clique via JavaScript realizado com sucesso.")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                logger.info("Página de edição carregada.")
                return True
        except Exception as e:
            logger.debug(f"Fallback JS falhou: {e}")

        if tentativa < 3:
            time.sleep(1)

    logger.error("Botão de Alterar NÃO encontrado após todas as tentativas.")
    return False


def processar_unidade(page: Page, target_unit: str, action: str) -> bool:
    """
    Navega pelas páginas da tabela de unidades até encontrar a unidade alvo.
    BLOQUEIO = desmarcar checkbox GET | DESBLOQUEIO = marcar checkbox GET.
    """
    logger.info(f"Iniciando busca pela unidade: {target_unit}")

    # Otimização: Tentar colocar 30 itens por página
    _tentar_aumentar_itens_por_pagina(page)

    page_num = 1
    while True:
        logger.info(f"Analisando página {page_num} da tabela de unidades...")
        
        # Espera a tabela estar visível
        tabela_linhas = page.locator("#form\\:tabelaUnidades_data tr")
        tabela_linhas.first.wait_for(state="visible", timeout=10000)
        
        count = tabela_linhas.count()
        logger.info(f"Encontradas {count} linhas na página atual.")

        for i in range(count):
            row = tabela_linhas.nth(i)
            unit_text = row.locator("td:nth-child(2)").text_content()

            if unit_text:
                match = re.search(r'(\d+)', unit_text)
                if match:
                    codigo_encontrado = match.group(1)

                    if codigo_encontrado == target_unit:
                        return _executar_acao_checkbox(row, unit_text, action)

        # Paginação
        next_btn = page.locator("[id=\"form\\:tabelaUnidades_paginator_bottom\"] a.ui-paginator-next:not(.ui-state-disabled)")
        if next_btn.count() > 0 and next_btn.is_visible():
            logger.info("Unidade não encontrada nesta página. Indo para próxima página...")
            next_btn.click()
            # Esperar a tabela atualizar (evita stale element)
            time.sleep(2) 
            page_num += 1
        else:
            logger.warning("Fim das páginas. Unidade ALVO NÃO encontrada em nenhuma página.")
            return False


def _tentar_aumentar_itens_por_pagina(page: Page):
    """Tenta alterar o dropdown de paginação para 30 itens."""
    try:
        dropdown = page.locator("[id=\"form\\:tabelaUnidades\\:j_id7\"]")
        if dropdown.count() > 0 and dropdown.is_visible(timeout=2000):
            page.select_option("[id=\"form\\:tabelaUnidades\\:j_id7\"]", "30")
            time.sleep(1)
            logger.debug("Itens por página alterado para 30.")
    except Exception:
        pass


def _executar_acao_checkbox(row, unit_text, action) -> bool:
    """Executa a marcação/desmarcação do checkbox."""
    logger.info(f"UNIDADE ALVO ENCONTRADA: {unit_text.strip()}")
    
    checkbox = row.locator('[id$="selecionarDeselecionarGet"]')

    if checkbox.is_visible():
        esta_marcado = checkbox.is_checked()
        logger.info(f"Estado checkbox 'GET': {'MARCADO' if esta_marcado else 'DESMARCADO'}")

        if action == "BLOQUEIO":
            if esta_marcado:
                logger.info("BLOQUEIO: Desmarcando checkbox 'GET'...")
                checkbox.uncheck()
                logger.info("Checkbox desmarcado com sucesso.")
            else:
                logger.info("BLOQUEIO: Já desmarcado. OK.")
        elif action == "DESBLOQUEIO":
            if not esta_marcado:
                logger.info("DESBLOQUEIO: Marcando checkbox 'GET'...")
                checkbox.check()
                logger.info("Checkbox marcado com sucesso.")
            else:
                logger.info("DESBLOQUEIO: Já marcado. OK.")
        else:
            logger.error(f"Ação inválida: {action}")
            return False

        return True
    else:
        logger.error("Checkbox 'GET' não encontrado ou invisível nesta linha.")
        return False


def confirmar_alteracao(page: Page) -> bool:
    """
    Clica no botão confirmar, lida com warnings e verifica sucesso.
    """
    logger.info("Iniciando confirmação das alterações...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    
    # Clica no botão Confirmar
    btn_confirmar = page.locator("id=form:botaoConfirmar")
    if btn_confirmar.is_visible():
        btn_confirmar.click()
    else:
        logger.info("Botão Playwright não visível, tentando JS...")
        page.evaluate("document.getElementById('form:botaoConfirmar').click()")
    
    # Aguarda processamento
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    # Verifica mensagens (Sucesso ou Divergência)
    for attempt in range(3):
        logger.info(f"Verificando resultado (Tentativa {attempt+1}/3)...")
        
        # 1. Sucesso
        if page.locator("text=Alteração realizada").first.is_visible(timeout=2000):
            logger.info("SUCESSO: Mensagem 'Alteração realizada' detectada!")
            return True

        # 2. Divergência (requer re-confirmação)
        if page.locator("text=diverge dos dados").first.is_visible(timeout=2000):
            logger.warning("AVISO DE DIVERGÊNCIA. Re-confirmando...")
            page.evaluate("document.getElementById('form:botaoConfirmar').click()")
            time.sleep(3)
            continue
            
        time.sleep(1)

    logger.error("FALHA: Mensagem de sucesso não detectada.")
    return False


def executar_bloqueio(siape: str, codigo_unidade: str, acao: str,
                      session_manager=None) -> tuple:
    """
    Executa uma operação de bloqueio ou desbloqueio no SAGGESTAO.

    Args:
        siape: SIAPE do servidor (ex: "2035843")
        codigo_unidade: Código da unidade (ex: "085211")
        acao: "BLOQUEIO" ou "DESBLOQUEIO"
        session_manager: Instância de SaggestaoSessionManager (opcional)

    Returns:
        Tupla (sucesso: bool, erro: str | None)
    """
    logger.info(f">>> EXECUTANDO {acao} | SIAPE={siape} | Unidade={codigo_unidade} <<<")

    if session_manager is not None:
        return _executar_com_sessao(siape, codigo_unidade, acao, session_manager)
    else:
        return _executar_standalone(siape, codigo_unidade, acao)


def _executar_com_sessao(siape, codigo_unidade, acao, session_manager):
    """Executa operação usando sessão persistente."""
    try:
        page = session_manager.ensure_ready()
        return _fluxo_principal(page, siape, codigo_unidade, acao, session_manager)
    except Exception as e:
        msg = f"Erro fatal durante {acao}: {str(e)}"
        logger.critical(msg, exc_info=True)
        return False, msg


def _executar_standalone(siape, codigo_unidade, acao):
    """Executa operação abrindo/fechando browser (modo CLI)."""
    try:
        with sync_playwright() as p:
            logger.info(f"Iniciando navegador (headless={BROWSER_HEADLESS})...")
            browser = p.chromium.launch(headless=BROWSER_HEADLESS)
            
            # Usa auth.py para obter contexto autenticado
            context = SaggestaoAuth.configurar_contexto(browser)
            page = context.new_page()
            
            page.set_default_timeout(PLAYWRIGHT_DEFAULT_TIMEOUT)
            page.goto(SAGGESTAO_CONSULTATION_URL)
            
            sucesso, erro = _fluxo_principal(page, siape, codigo_unidade, acao)
            
            browser.close()
            return sucesso, erro
    except Exception as e:
        msg = f"Erro fatal standalone: {str(e)}"
        logger.critical(msg)
        return False, msg


def _fluxo_principal(page: Page, siape, codigo_unidade, acao, session_manager=None):
    """Lógica core compartilhada entre modo sessão e standalone."""
    max_tentativas_busca = MAX_RETRIES

    # Etapa 1: Buscar servidor (com retry completo)
    busca_ok = False
    for tentativa in range(1, max_tentativas_busca + 1):
        if buscar_servidor(page, siape):
            busca_ok = True
            break

        if tentativa < max_tentativas_busca:
            logger.warning(
                f"Busca/Alterar falhou (tentativa {tentativa}/{max_tentativas_busca}). "
                f"Resetando busca e tentando novamente..."
            )
            _resetar_busca(page, session_manager)
        else:
            logger.error(f"Busca falhou após {max_tentativas_busca} tentativas.")

    if not busca_ok:
        if session_manager:
            session_manager.navigate_to_consultation()
        return False, f"Servidor {siape} não encontrado após {max_tentativas_busca} tentativas."

    # Etapa 2: Unidade e Checkbox
    if not processar_unidade(page, codigo_unidade, acao):
        if session_manager:
            session_manager.navigate_to_consultation()
        return False, f"Unidade {codigo_unidade} não encontrada ou erro."

    # Etapa 3: Confirmar
    if not confirmar_alteracao(page):
        if session_manager:
            session_manager.navigate_to_consultation()
        return False, "Falha na confirmação."

    logger.info(f">>> {acao} CONCLUÍDO | SIAPE={siape} <<<")

    if session_manager:
        session_manager.navigate_to_consultation()
        session_manager.mark_activity()

    return True, None


def _resetar_busca(page: Page, session_manager=None):
    """Reseta a página de consulta para uma nova tentativa de busca."""
    try:
        if session_manager:
            session_manager.navigate_to_consultation()
        else:
            page.goto(SAGGESTAO_CONSULTATION_URL, timeout=PLAYWRIGHT_DEFAULT_TIMEOUT)
        page.wait_for_selector('input[name="form\\:idMskSiape"]', timeout=15000)
        time.sleep(1)
    except Exception as e:
        logger.warning(f"Erro ao resetar busca: {e}")


def main():
    """CLI para testes manuais."""
    if len(sys.argv) == 4:
        siape = sys.argv[1]
        codigo_unidade = sys.argv[2]
        acao = sys.argv[3].upper()
    elif len(sys.argv) == 1:
        siape = input("SIAPE: ").strip()
        codigo_unidade = input("Código da Unidade: ").strip()
        acao = input("Ação (BLOQUEIO/DESBLOQUEIO): ").strip().upper()
    else:
        print("Uso: python bloquear_perfis.py <SIAPE> <CODIGO_UNIDADE> <BLOQUEIO|DESBLOQUEIO>")
        sys.exit(1)

    sucesso, erro = executar_bloqueio(siape, codigo_unidade, acao)

    if sucesso:
        logger.info("Resultado: SUCESSO")
    else:
        logger.error(f"Resultado: FALHA - {erro}")
        sys.exit(1)


if __name__ == "__main__":
    main()
