import time
import requests
import urllib3
import re
import logging
import sys
from playwright.sync_api import sync_playwright

# --- CONFIGURAÇÃO DE LOG ---
# Configura o logger para exibir mensagens no terminal com timestamp e nível
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("BloqueadorPerfis")

# --- CONFIGURAÇÃO ---
# Substitua pelos valores reais que deseja testar
TARGET_SIAPE = "2035843"  # Exemplo hardcoded
TARGET_UNIT = "085211"     # Exemplo hardcoded: Código da unidade
ACTION = "DESBLOQUEIO"          # BLOQUEIO = desmarcar checkbox GET | DESBLOQUEIO = marcar checkbox GET

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
            time.sleep(2) # Aguarda antes da próxima tentativa

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

    logger.info("Iniciando navegador Playwright...")
    browser = p.chromium.launch(headless=False)
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
        # Tenta identificar o seletor de domínios com timeout curto (5s)
        if page.locator("select#domains").is_visible(timeout=5000):
            logger.info("Página de seleção de domínio DETECTADA. Iniciando seleção da unidade...")
            logger.info("Selecionando unidade 'UO:01.001.PRES'...")
            page.select_option("select#domains", "UO:01.001.PRES")
            
            logger.info("Clicando no botão 'Enviar'...")
            page.get_by_role("button", name="Enviar").click()
            
            logger.info("Aguardando carregamento da página pós-seleção...")
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2) # Pequena pausa para estabilização
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
        # Mesmo com erro, vamos tentar retornar para que o script decida o que fazer
    
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


def processar_unidade(page, target_unit, action=ACTION):
    """
    Navega pelas páginas da tabela de unidades até encontrar a unidade alvo.
    BLOQUEIO = desmarcar checkbox GET | DESBLOQUEIO = marcar checkbox GET.
    """
    logger.info(f"Iniciando busca pela unidade: {target_unit}")
    
    # Otimização: Tentar colocar 30 itens por página
    try:
        logger.info("Tentando aumentar itens por página para 30...")
        page.select_option("[id=\"form\\:tabelaUnidades\\:j_id7\"]", "30")
        time.sleep(2)
    except:
        logger.debug("Não foi possível alterar itens por página (pode não estar disponível).")
        pass

    page_num = 1
    while True:
        logger.info(f"Analisando página {page_num} da tabela de unidades...")
        # Itera sobre as linhas da tabela
        rows = page.locator("#form\\:tabelaUnidades_data tr")
        count = rows.count()
        logger.info(f"Encontradas {count} linhas na página atual.")
        
        for i in range(count):
            row = rows.nth(i)
            # A coluna da unidade é geralmente a 2ª (índice 1 no texto, ou nth-child(2))
            unit_text = row.locator("td:nth-child(2)").text_content()
            
            # Extrai apenas os números do texto da unidade
            if unit_text:
                match = re.search(r'(\d+)', unit_text)
                if match:
                    codigo_encontrado = match.group(1)
                    # logger.debug(f"Linha {i+1}: Unidade {codigo_encontrado} - {unit_text.strip()[:30]}...")
                    
                    if codigo_encontrado == target_unit:
                        logger.info(f"UNIDADE ALVO ENCONTRADA na linha {i+1}: {unit_text.strip()}")
                        logger.info(f"Ação configurada: {action}")
                        
                        # Localiza o checkbox
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
            time.sleep(2) # Aguarda carregar
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
    # Rola até o fim para garantir visibilidade
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)
    
    # Verifica se o botão existe no DOM
    btn_exists = page.evaluate("!!document.getElementById('form:botaoConfirmar')")
    
    if btn_exists:
        logger.info("Botão Confirmar encontrado no DOM. Clicando via JavaScript...")
        page.evaluate("document.getElementById('form:botaoConfirmar').click()")
        time.sleep(3) # Aguarda processamento inicial (submit do formulário)
        
        # Aguarda carregamento da página resultante
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.info("Página pós-confirmação carregada.")
        except Exception as e:
            logger.warning(f"Timeout aguardando carregamento pós-confirmação: {e}")
        
        # Loop de verificação para lidar com warnings ou lentidão
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
            # Verifica APENAS no #mMensagens para evitar strict mode violation
            divergencia_locator = page.locator("#mMensagens").locator("text=diverge dos dados")
            try:
                if divergencia_locator.count() > 0 and divergencia_locator.first.is_visible():
                    logger.warning("AVISO DE DIVERGÊNCIA detectado em #mMensagens ('Horário diverge').")
                    logger.info("Confirmando novamente via JavaScript...")
                    
                    # Usa JavaScript para clicar (mais confiável com PrimeFaces)
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
                    
                    continue # Volta para verificar sucesso
            except Exception as e:
                logger.debug(f"Exceção ao verificar divergência: {e}")
            
            # 3. Se ainda não achou nada, espera um pouco e tenta checar de novo
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

def main():
    logger.info(">>> INICIANDO SCRIPT DE BLOQUEIO DE PERFIS <<<")
    with sync_playwright() as p:
        try:
            browser, context, page = login_e_navegar(p)
            
            if buscar_servidor(page, TARGET_SIAPE):
                if processar_unidade(page, TARGET_UNIT):
                    if confirmar_alteracao(page):
                        logger.info("Processo completo realizado com EXITO.")
                    else:
                         logger.error("Falha na etapa de confirmação.")
                else:
                    logger.error("Falha ao processar a unidade (não encontrada ou erro no checkbox).")
            else:
                 logger.error("Falha ao buscar o servidor.")
            
            logger.info("Encerrando navegador...")
            browser.close()
            
        except Exception as e:
            logger.critical(f"ERRO FATAL NA EXECUÇÃO: {e}", exc_info=True)

    logger.info(">>> EXECUÇÃO FINALIZADA <<<")

if __name__ == "__main__":
    main()
