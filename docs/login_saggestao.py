import json
import requests
import urllib3
from colorama import Fore, Style, init

# Importa a biblioteca Playwright
from playwright.sync_api import sync_playwright

# Inicializa colorama
init(autoreset=True)

# Desativa avisos de SSL para a requisição local
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def obter_jsessionid_local():
    """
    Faz uma requisição GET para o servidor local para obter o valor do JSESSIONID.
    """
    print(f"{Fore.CYAN}╔═══════════════════════════════════╗")
    print(f"{Fore.CYAN}║{Style.BRIGHT}  CONSULTANDO SERVIDOR LOCAL...  {Style.NORMAL}║")
    print(f"{Fore.CYAN}╚═══════════════════════════════════╝{Style.RESET_ALL}\n")
    
    url = "http://localhost:48000"
    headers = {'Comando': 'NovaSessao', 'Sistema': 'SAGGESTAO'}

    print(f"{Fore.YELLOW}Realizando requisição para {url}...{Style.RESET_ALL}")

    try:
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code == 200:
            print(f"{Fore.GREEN}Requisição ao servidor local bem-sucedida!{Style.RESET_ALL}\n")
            data = response.json()
            jsessionid = data.get('JSESSIONID')
            if jsessionid:
                print(f"{Fore.GREEN}JSESSIONID encontrado com sucesso!{Style.RESET_ALL}")
                return jsessionid
            else:
                print(f"{Fore.RED}A chave 'JSESSIONID' não foi encontrada na resposta JSON.{Style.RESET_ALL}")
                print("Dados recebidos:", data)
                return None
        else:
            print(f"{Fore.RED}Erro no servidor local: código de status {response.status_code}{Style.RESET_ALL}")
            return None
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        print(f"{Fore.RED}Erro ao comunicar com o servidor local: {e}{Style.RESET_ALL}")
        return None

def main():
    """
    Função principal que obtém o JSESSIONID e o injeta em um navegador Playwright.
    """
    valor_jsessionid = obter_jsessionid_local()

    if not valor_jsessionid:
        print(f"{Fore.RED}Não foi possível obter o JSESSIONID. Abortando.{Style.RESET_ALL}")
        return

    with sync_playwright() as p:
        print("\n" + Fore.CYAN + "╔═══════════════════════════════════╗")
        print(f"{Fore.CYAN}║{Style.BRIGHT}  INICIANDO NAVEGADOR PLAYWRIGHT {Style.NORMAL}║")
        print(Fore.CYAN + "╚═══════════════════════════════════╝" + Style.RESET_ALL + "\n")

        browser = p.chromium.launch(headless=False)
        
        # ### ALTERAÇÃO CRÍTICA AQUI ###
        # Adicionamos 'ignore_https_errors=True' para que o navegador não pare
        # na tela de "Erro de privacidade".
        context = browser.new_context(ignore_https_errors=True)
        print(f"{Fore.GREEN}Navegador iniciado com sucesso (ignorando erros de SSL).{Style.RESET_ALL}")

        print(f"{Fore.YELLOW}Injetando o cookie JSESSIONID para o domínio 'psagapr01'...{Style.RESET_ALL}")
        
        cookie_para_injetar = {
            "name": "JSESSIONID",
            "value": valor_jsessionid,
            "url": "https://psagapr01"
        }

        context.add_cookies([cookie_para_injetar])
        print(f"{Fore.GREEN}Cookie injetado com sucesso!{Style.RESET_ALL}")

        page = context.new_page()
        url_destino = "https://psagapr01/saggestaoagu/pages/comum/gpa/domainSelection.xhtml"
        print(f"{Fore.YELLOW}Navegando diretamente para a página de seleção de domínio...{Style.RESET_ALL}")
        
        # Agora o .goto() não vai mais falhar por causa do erro de certificado
        page.goto(url_destino)
        
        page.get_by_role("button", name="Enviar").click()

        print(f"\n{Fore.GREEN}PROCESSO CONCLUÍDO!{Style.RESET_ALL}")
        print(f"{Fore.CYAN}O navegador deve estar na página de seleção de domínio, com o login já efetuado.{Style.RESET_ALL}")
        
        input("\nPressione ENTER para fechar o navegador...")
        browser.close()

if __name__ == "__main__":
    main()