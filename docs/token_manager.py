import requests
import urllib3
import json
from colorama import Fore, Style, init
import time
from datetime import datetime

# Inicializa colorama para colorir o terminal
init(autoreset=True)

def requisitar_localhost():
    """
    Faz uma requisição GET para o servidor local e exibe as informações retornadas.
    """
    print()
    # Título formatado
    titulo_texto = "  CONSULTA LOCALHOST  "
    linha_superior = "╔" + "═" * len(titulo_texto) + "╗"
    linha_inferior = "╚" + "═" * len(titulo_texto) + "╝"
    
    art = f"""
    {Fore.CYAN}{linha_superior}
    {Fore.CYAN}║{Style.BRIGHT}{titulo_texto}{Style.NORMAL}║
    {Fore.CYAN}{linha_inferior}{Style.RESET_ALL}
    """
    print(art)
    
    # Desativando warnings de SSL
    urllib3.disable_warnings()
    requests.packages.urllib3.disable_warnings()

    url = "http://localhost:48000"

    # headers = {
    #     'Comando': 'NovaSessao',
    #     'Sistema': 'PAT',
    #     'Papel': 'GESTOR_UNIDADE',
    #     'Dominio': '23.150.521'
    # }
    
    headers={'Comando':'NovaSessao', 'Sistema':'SAGGESTAO'}

    print(f"{Fore.YELLOW}Realizando requisição para {url}...{Style.RESET_ALL}")
    time.sleep(1)

    try:
        response = requests.get(url, headers=headers, verify=False)
        
        print()
        print(f"{Fore.CYAN}Status da resposta: {Fore.WHITE}{response.status_code}{Style.RESET_ALL}")

        if response.status_code == 200:
            print(f"{Fore.GREEN}Requisição bem-sucedida!{Style.RESET_ALL}\n")
            
            try:
                data = response.json()
                print(f"{Fore.CYAN}Dados retornados:{Style.RESET_ALL}")
                print(json.dumps(data, indent=4, ensure_ascii=False))
                print()
                print(f"{Fore.GREEN}Consulta realizada em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}{Style.RESET_ALL}")
            except json.JSONDecodeError:
                print(f"{Fore.RED}A resposta não está em formato JSON:{Style.RESET_ALL}")
                print(response.text)

        else:
            print(f"{Fore.RED}Erro: código de status {response.status_code}{Style.RESET_ALL}")
            print(f"Resposta: {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}Erro de conexão:{Style.RESET_ALL} {e}")
        print(f"{Fore.YELLOW}Verifique se o servidor Java está rodando e escutando na porta 47000.{Style.RESET_ALL}")

if __name__ == "__main__":
    requisitar_localhost()
