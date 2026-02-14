"""
Módulo de automação do SAGGESTAO para bloqueio/desbloqueio de perfis.

Contém a lógica de browser automation (Playwright) para interagir com o
sistema legado SAGGESTAO. Pode ser usado como módulo importado pelo
servico_rpa.py ou executado diretamente via CLI para testes.
"""

import time
import requests
import urllib3
import re
import logging
import sys
from playwright.sync_api import sync_playwright
from colored_logger import setup_colored_logging
from config import BROWSER_HEADLESS

# --- CONFIGURAÇÃO DE LOG COM CORES ---
setup_colored_logging(log_level=logging.INFO)
logger = logging.getLogger("BloqueadorPerfis")

# Desativa avisos de SSL para localhost e servidores internos
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def obter_jsessionid_local():
    """
    Obtém o JSESSIONID do servidor local (localhost:48000).
    Retorna a string do ID ou None se falhar.
    Tenta até 4 vezes (1 tentativa + 3 retries) em caso de erro.
    """
    logger.info("Iniciando obtenção de JSESSIONID...")
    url = "http://localhost:48000"
    headers = {'Comando': 'NovaSessao', 'Sistema': 'SAGGESTAO'}
    max_retries = 4

    for attempt in range(1, max_retries + 1):
        logger.info(f"Tentativa {attempt}/{max_retries} obtendo sessão de {url}...")
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=10)
            if response.status_code == 200:
                data = response.json()
                jsessionid = data.get('JSESSIONID')
                if jsessionid:
                    logger.info(f"JSESSIONID obtido com sucesso: {jsessionid[:10]}...")
                    return jsessionid
            else:
                logger.warning(f"Resposta inválida na tentativa {attempt}: Status {response.status_code}")
        except Exception as e:
            logger.error(f"Erro na tentativa {attempt}: {e}")

        if attempt < max_retries:
            logger.info("Aguardando 2 segundos antes da próxima tentativa...")
            time.sleep(2)

    logger.critical("Falha ao obter JSESSIONID após todas as tentativas.")
    return None


def login_e_navegar(p):
    """
    Realiza o login injetando o cookie e navega para a página de consulta.
    Retorna (browser, context, page) ou levanta exceção.
    """
    logger.info("Iniciando processo de Login e Navegação...")
    jsessionid = obter_jsessionid_local()
    if not jsessionid:
        logger.critical("Abortando: Falha ao obter JSESSIONID do servidor local.")
        raise Exception("Falha ao obter JSESSIONID do servidor local.")

    logger.info(f"Iniciando navegador Playwright (headless={BROWSER_HEADLESS})...")
    browser = p.chromium.launch(headless=BROWSER_HEADLESS)
    context = browser.new_context(ignore_https_errors=True)

    # Injeta o cookie
    logger.info("Injetando cookie JSESSIONID...")
    context.add_cookies([{
        "name": "JSESSIONID",
        "value": jsessionid,
        "url": "http://psagapr01"
    }])

    page = context.new_page()
    page.set_default_timeout(60000)
    page.set_viewport_size({"width": 1024, "height": 768})

    target_url = "http://psagapr01/saggestaoagu/pages/cadastro/profissional/consultar.xhtml"
    logger.info(f"Navegando para URL de consulta: {target_url}")

    # Primeira tentativa de navegação
    try:
        page.goto(target_url, timeout=120000)
        logger.info("Navegação inicial concluída.")
    except Exception as e:
        logger.warning(f"Aviso durante a navegação inicial: {e}")

    # Verifica se caiu na página de seleção de domínio (fluxo intermediário)
    logger.info("Verificando se houve redirecionamento para seleção de domínio...")
    try:
        if page.locator("select#domains").is_visible(timeout=5000):
            logger.info("Página de seleção de domínio DETECTADA. Iniciando seleção da unidade...")
            logger.info("Selecionando unidade 'UO:01.001.PRES'...")
            page.select_option("select#domains", "UO:01.001.PRES")

            logger.info("Clicando no botão 'Enviar'...")
            page.get_by_role("button", name="Enviar").click()

            logger.info("Aguardando carregamento da página pós-seleção...")
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            logger.info("Seleção de domínio concluída.")
        else:
            logger.info("Página de seleção de domínio NÃO detectada. Seguindo fluxo normal.")
    except Exception as e:
        logger.debug(f"Exceção não-crítica ao verificar seleção de domínio: {e}")
        pass

    # Se após o login/domínio caímos na home ou em outra página, forçamos a ida para a consulta
    current_url = page.url
    if "consultar.xhtml" not in current_url:
        logger.warning(f"Redirecionado inesperadamente para: {current_url}. Forçando navegação para consulta...")
        try:
             page.goto(target_url, timeout=60000)
             logger.info("Navegação forçada concluída.")
        except Exception as e:
             logger.error(f"Erro ao forçar navegação: {e}")

    # Verifica se carregou (procura pelo campo de SIAPE ou título)
    logger.info("Aguardando carregamento completo da página de consulta...")
    try:
        page.wait_for_selector('input[name="form\\:idMskSiape"]', timeout=30000)
        logger.info("Página de consulta carregada com SUCESSO.")
    except:
        logger.error("Tempo limite excedido aguardando página de consulta.")
        logger.error(f"URL atual: {page.url}")

    return browser, context, page


def buscar_servidor(page, siape):
    """
    Busca o servidor pelo SIAPE e clica em alterar.
    Inclui retries e fallback JS para o botão de alterar.
    """
    logger.info(f"Iniciando busca pelo servidor com SIAPE: {siape}")
    try:
        page.fill('input[name="form\\:idMskSiape"]', siape)
        logger.info("Campo SIAPE preenchido.")

        logger.info("Clicando em 'Pesquisar'...")
        page.click('role=button[name="Pesquisar"]')

        # Aguarda resultados
        time.sleep(2)

        # Verifica se encontrou
        if page.locator("text=Nao foram encontrados registros").or_(page.locator("text=Não foram encontrados registros")).first.is_visible():
            logger.warning(f"Servidor com SIAPE {siape} NAO encontrado.")
            return False

        # Clica em Alterar com retries e fallback JS
        logger.info("Registro encontrado. Procurando botao de Alterar...")

        seletores = [
            '[id$="idAlterarCadastroProfissional"]',
            'a.ico-pencil',
            'role=link[name=""]',
        ]

        for tentativa in range(1, 4):
            logger.info(f"Tentativa {tentativa}/3 para clicar no botao Alterar...")

            for sel in seletores:
                try:
                    btn = page.locator(sel)
                    if btn.count() > 0 and btn.first.is_visible():
                        logger.info(f"Botao encontrado via seletor: {sel}")
                        btn.first.click()
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        logger.info("Pagina de edicao carregada.")
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
                        const pencils = document.querySelectorAll('a.ico-pencil');
                        if (pencils.length > 0) { pencils[0].click(); return true; }
                        return false;
                    })()
                """)
                if clicked:
                    logger.info("Clique via JavaScript realizado com sucesso.")
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    logger.info("Pagina de edicao carregada.")
                    return True
            except Exception as e:
                logger.debug(f"Fallback JS falhou: {e}")

            if tentativa < 3:
                logger.warning("Botao nao encontrado. Aguardando 2s...")
                time.sleep(2)

        logger.error("Botao de Alterar NAO encontrado apos todas as tentativas.")
        return False

    except Exception as e:
        logger.error(f"Erro durante a busca do servidor: {e}")
        return False


def processar_unidade(page, target_unit, action):
    """
    Navega pelas páginas da tabela de unidades até encontrar a unidade alvo.
    BLOQUEIO = desmarcar checkbox GET | DESBLOQUEIO = marcar checkbox GET.

    Args:
        page: Página do Playwright
        target_unit: Código da unidade alvo (ex: "085211")
        action: "BLOQUEIO" ou "DESBLOQUEIO"
    """
    logger.info(f"Iniciando busca pela unidade: {target_unit}")

    # Otimização: Tentar colocar 30 itens por página (timeout rápido para não travar)
    try:
        logger.info("Tentando aumentar itens por página para 30...")
        dropdown = page.locator("[id=\"form\\:tabelaUnidades\\:j_id7\"]")
        if dropdown.count() > 0 and dropdown.is_visible(timeout=2000):
            page.select_option("[id=\"form\\:tabelaUnidades\\:j_id7\"]", "30")
            time.sleep(1)
            logger.debug("Itens por página alterado para 30.")
        else:
            logger.debug("Dropdown de itens por página não encontrado (tabela pequena).")
    except Exception as e:
        logger.debug(f"Não foi possível alterar itens por página: {e}")

    page_num = 1
    while True:
        logger.info(f"Analisando página {page_num} da tabela de unidades...")
        rows = page.locator("#form\\:tabelaUnidades_data tr")
        count = rows.count()
        logger.info(f"Encontradas {count} linhas na página atual.")

        for i in range(count):
            row = rows.nth(i)
            unit_text = row.locator("td:nth-child(2)").text_content()

            if unit_text:
                match = re.search(r'(\d+)', unit_text)
                if match:
                    codigo_encontrado = match.group(1)

                    if codigo_encontrado == target_unit:
                        logger.info(f"UNIDADE ALVO ENCONTRADA na linha {i+1}: {unit_text.strip()}")
                        logger.info(f"Ação configurada: {action}")

                        checkbox = row.locator('[id$="selecionarDeselecionarGet"]')

                        if checkbox.is_visible():
                            esta_marcado = checkbox.is_checked()
                            logger.info(f"Estado atual do checkbox 'GET': {'MARCADO' if esta_marcado else 'DESMARCADO'}")

                            if action == "BLOQUEIO":
                                if esta_marcado:
                                    logger.info("BLOQUEIO: Desmarcando checkbox 'GET'...")
                                    checkbox.uncheck()
                                    logger.info("Checkbox desmarcado com sucesso.")
                                else:
                                    logger.info("BLOQUEIO: Checkbox já estava desmarcado. Nenhuma ação necessária.")
                            elif action == "DESBLOQUEIO":
                                if not esta_marcado:
                                    logger.info("DESBLOQUEIO: Marcando checkbox 'GET'...")
                                    checkbox.check()
                                    logger.info("Checkbox marcado com sucesso.")
                                else:
                                    logger.info("DESBLOQUEIO: Checkbox já estava marcado. Nenhuma ação necessária.")
                            else:
                                logger.error(f"Ação inválida: '{action}'. Use 'BLOQUEIO' ou 'DESBLOQUEIO'.")
                                return False

                            return True
                        else:
                            logger.error("Checkbox 'GET' não encontrado ou invisível nesta linha.")
                            return False

        # Paginação
        next_btn = page.locator("[id=\"form\\:tabelaUnidades_paginator_bottom\"] a.ui-paginator-next:not(.ui-state-disabled)")
        if next_btn.count() > 0 and next_btn.is_visible():
            logger.info("Unidade não encontrada nesta página. Indo para próxima página...")
            next_btn.click()
            time.sleep(2)
            page_num += 1
        else:
            logger.warning("Fim das páginas. Unidade ALVO NÃO encontrada em nenhuma página.")
            return False


def confirmar_alteracao(page):
    """
    Clica no botão confirmar e verifica mensagens de sucesso, lidando com warnings de divergência.
    Usa JavaScript para clicar no botão (mais confiável com PrimeFaces).
    Verifica divergência apenas no #mMensagens para evitar ambiguidade com dialogs ocultos.
    """
    logger.info("Iniciando confirmação das alterações...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)

    btn_exists = page.evaluate("!!document.getElementById('form:botaoConfirmar')")

    if btn_exists:
        logger.info("Botão Confirmar encontrado no DOM. Clicando via JavaScript...")
        page.evaluate("document.getElementById('form:botaoConfirmar').click()")
        time.sleep(3)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.info("Página pós-confirmação carregada.")
        except Exception as e:
            logger.warning(f"Timeout aguardando carregamento pós-confirmação: {e}")

        for attempt in range(3):
            logger.info(f"Verificando resultado da confirmação (Tentativa {attempt+1}/3)...")
            logger.info(f"URL atual: {page.url}")

            # 1. Sucesso direto
            success_locator = page.locator("#mMensagens").locator("text=Alteração realizada")
            try:
                if success_locator.count() > 0 and success_locator.first.is_visible():
                    logger.info("SUCESSO: Mensagem 'Alteração realizada' detectada em #mMensagens!")
                    return True
            except Exception:
                pass

            # Fallback: verifica sucesso em qualquer lugar da página
            try:
                if page.locator("text=Alteração realizada").first.is_visible():
                    logger.info("SUCESSO: Mensagem 'Alteração realizada' detectada na página!")
                    return True
            except Exception:
                pass

            # 2. Aviso de divergência (requer nova confirmação)
            divergencia_locator = page.locator("#mMensagens").locator("text=diverge dos dados")
            try:
                if divergencia_locator.count() > 0 and divergencia_locator.first.is_visible():
                    logger.warning("AVISO DE DIVERGÊNCIA detectado em #mMensagens ('Horário diverge').")
                    logger.info("Confirmando novamente via JavaScript...")

                    btn_still_exists = page.evaluate("!!document.getElementById('form:botaoConfirmar')")
                    if btn_still_exists:
                        logger.info("Clicando no botão Confirmar via JS...")
                        page.evaluate("document.getElementById('form:botaoConfirmar').click()")
                    else:
                        logger.warning("Botão 'form:botaoConfirmar' não encontrado no DOM. Tentando submit do formulário...")
                        page.evaluate("document.getElementById('form').submit()")

                    logger.info("Aguardando processamento pós-reconfirmação...")
                    time.sleep(3)

                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass

                    continue
            except Exception as e:
                logger.debug(f"Exceção ao verificar divergência: {e}")

            logger.debug("Nenhuma mensagem definitiva encontrada. Aguardando...")
            time.sleep(2)

        # Última verificação após o loop
        try:
            if page.locator("text=Alteração realizada").first.is_visible():
                logger.info("SUCESSO: Alteração realizada com sucesso (após verificações)!")
                return True
        except Exception:
            pass

        logger.error("FALHA: Mensagem de sucesso não detectada após todas as tentativas.")
        logger.error(f"URL final: {page.url}")
        return False
    else:
        logger.error("Botão Confirmar NÃO encontrado no DOM da página.")
        return False


def executar_bloqueio(siape: str, codigo_unidade: str, acao: str,
                      session_manager=None) -> tuple:
    """
    Executa uma operação de bloqueio ou desbloqueio no SAGGESTAO.

    Se session_manager é fornecido, usa a sessão persistente (modo serviço).
    Caso contrário, abre/fecha browser como antes (modo standalone/CLI).

    Args:
        siape: SIAPE do servidor (ex: "2035843")
        codigo_unidade: Código da unidade (ex: "085211")
        acao: "BLOQUEIO" ou "DESBLOQUEIO"
        session_manager: Instância de SaggestaoSessionManager (opcional)

    Returns:
        Tupla (sucesso: bool, erro: str | None)
        - (True, None) se a operação foi concluída com sucesso
        - (False, "mensagem de erro") se houve falha
    """
    logger.info(f">>> EXECUTANDO {acao} | SIAPE={siape} | Unidade={codigo_unidade} <<<")

    if acao not in ("BLOQUEIO", "DESBLOQUEIO"):
        return (False, f"Ação inválida: '{acao}'. Use 'BLOQUEIO' ou 'DESBLOQUEIO'.")

    if session_manager is not None:
        return _executar_com_sessao_persistente(siape, codigo_unidade, acao, session_manager)
    else:
        return _executar_standalone(siape, codigo_unidade, acao)


def _executar_com_sessao_persistente(siape, codigo_unidade, acao, session_manager):
    """Executa operação usando sessão persistente do SessionManager."""
    try:
        page = session_manager.ensure_ready()

        # Etapa 1: Buscar servidor
        if not buscar_servidor(page, siape):
            session_manager.navigate_to_consultation()
            msg = f"Servidor com SIAPE {siape} não encontrado no SAGGESTAO."
            logger.error(msg)
            return (False, msg)

        # Etapa 2: Processar unidade (marcar/desmarcar checkbox)
        if not processar_unidade(page, codigo_unidade, acao):
            session_manager.navigate_to_consultation()
            msg = f"Unidade {codigo_unidade} não encontrada ou erro ao processar checkbox."
            logger.error(msg)
            return (False, msg)

        # Etapa 3: Confirmar alteração
        if not confirmar_alteracao(page):
            session_manager.navigate_to_consultation()
            msg = "Falha na confirmação: mensagem de sucesso não detectada no SAGGESTAO."
            logger.error(msg)
            return (False, msg)

        logger.info(f">>> {acao} CONCLUÍDO COM SUCESSO | SIAPE={siape} | Unidade={codigo_unidade} <<<")

        # Volta à pagina de consulta e reseta timer
        session_manager.navigate_to_consultation()
        session_manager.mark_activity()
        return (True, None)

    except Exception as e:
        msg = f"Erro fatal durante {acao}: {str(e)}"
        logger.critical(msg, exc_info=True)
        return (False, msg)


def _executar_standalone(siape, codigo_unidade, acao):
    """Executa operação abrindo/fechando browser (modo CLI standalone)."""
    browser = None
    try:
        with sync_playwright() as p:
            browser, context, page = login_e_navegar(p)

            # Etapa 1: Buscar servidor
            if not buscar_servidor(page, siape):
                browser.close()
                msg = f"Servidor com SIAPE {siape} não encontrado no SAGGESTAO."
                logger.error(msg)
                return (False, msg)

            # Etapa 2: Processar unidade (marcar/desmarcar checkbox)
            if not processar_unidade(page, codigo_unidade, acao):
                browser.close()
                msg = f"Unidade {codigo_unidade} não encontrada ou erro ao processar checkbox."
                logger.error(msg)
                return (False, msg)

            # Etapa 3: Confirmar alteração
            if not confirmar_alteracao(page):
                browser.close()
                msg = "Falha na confirmação: mensagem de sucesso não detectada no SAGGESTAO."
                logger.error(msg)
                return (False, msg)

            logger.info(f">>> {acao} CONCLUÍDO COM SUCESSO | SIAPE={siape} | Unidade={codigo_unidade} <<<")
            browser.close()
            return (True, None)

    except Exception as e:
        msg = f"Erro fatal durante {acao}: {str(e)}"
        logger.critical(msg, exc_info=True)
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        return (False, msg)


def main():
    """
    Ponto de entrada para execução direta via CLI (para testes manuais).

    Uso:
        python bloquear_perfis.py <SIAPE> <CODIGO_UNIDADE> <BLOQUEIO|DESBLOQUEIO>

    Exemplo:
        python bloquear_perfis.py 2035843 085211 DESBLOQUEIO
    """
    if len(sys.argv) == 4:
        siape = sys.argv[1]
        codigo_unidade = sys.argv[2]
        acao = sys.argv[3].upper()
    elif len(sys.argv) == 1:
        # Fallback interativo para testes rápidos
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
