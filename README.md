# RPA Bloqueador de Perfis SAGGESTAO

Serviço de automação para bloqueio/desbloqueio de perfis de servidores no sistema legado SAGGESTAO, integrado com a API do Sistema SIGA.

## Início Rápido

### 1. Configurar Credenciais

Editar `config.py`:

```python
SIGA_API_URL = "http://localhost:8000"  # URL da API SIGA
SIGA_EMAIL = "rpa@inss.gov.br"         # Email da conta staff
SIGA_PASSWORD = "senha-do-rpa"         # Senha da conta
```

Ou usar variáveis de ambiente:

```bash
set SIGA_EMAIL=rpa@inss.gov.br
set SIGA_PASSWORD=senha-segura
```

### 2. Criar Conta RPA no Django

```bash
cd f:\Sistema SIGA\backend
python manage.py shell
```

```python
from usuarios.models import CustomUser
CustomUser.objects.create_user(
    email='rpa@inss.gov.br',
    siape='0000001',
    password='senha-segura',
    nome_completo='RPA Bloqueador',
    cpf='00000000000',
    is_staff=True  # Obrigatório!
)
```

### 3. Executar o Serviço

```bash
python servico_rpa.py
```

**Para encerrar:** Ctrl+C

## Arquivos

- **servico_rpa.py** - Loop principal de polling (executar este)
- **bloquear_perfis.py** - Lógica de automação do SAGGESTAO com Playwright
- **siga_client.py** - Cliente HTTP para API SIGA com autenticação JWT
- **config.py** - Configurações (API URL, credenciais, intervalos)
- **rpa_bloqueios.log** - Log de execução

## Como Funciona

1. **Polling:** Busca bloqueios/desbloqueios pendentes na API SIGA a cada 30 segundos
2. **Automação:** Para cada pedido, abre navegador Chrome, faz login no SAGGESTAO, localiza servidor e unidade, modifica checkbox GET
3. **Confirmação:** Reporta sucesso/erro de volta à API SIGA
4. **Loop:** Aguarda intervalo e repete

## Comandos Úteis

### Teste Manual de Bloqueio
```bash
python bloquear_perfis.py <SIAPE> <CODIGO_UNIDADE> <BLOQUEIO|DESBLOQUEIO>

# Exemplo:
python bloquear_perfis.py 2035843 085211 BLOQUEIO
```

### Verificar Logs
```bash
# Windows
type rpa_bloqueios.log

# PowerShell
Get-Content rpa_bloqueios.log -Tail 50
```

### Instalar como Serviço Windows (NSSM)
```cmd
nssm install RpaBloqueiosPerfis
# Path: F:\PYTHON\Bloqueador de Perfis SAGGESTAO\venv\Scripts\python.exe
# Arguments: servico_rpa.py
# Startup directory: F:\PYTHON\Bloqueador de Perfis SAGGESTAO

nssm start RpaBloqueiosPerfis
```

## Pré-requisitos

- Python 3.13+ com venv
- Playwright: `pip install playwright && playwright install chromium`
- Servidor Java de autenticação: `localhost:48000`
- Certificado digital configurado
- Acesso à rede interna (SAGGESTAO em `http://psagapr01`)

## Troubleshooting

### "Falha ao obter JSESSIONID"
→ Iniciar servidor Java em localhost:48000

### "Falha na autenticação: HTTP 401"
→ Verificar email/senha em config.py

### "Sem conexão com a API SIGA"
→ Iniciar backend Django: `python manage.py runserver`

### "Servidor com SIAPE X não encontrado"
→ SIAPE não existe no SAGGESTAO ou está inválido

### "Unidade X não encontrada"
→ Servidor não tem acesso a essa unidade no SAGGESTAO

## Documentação Completa

Documentação detalhada: `f:\Sistema SIGA\backend\RPA_BLOQUEIOS.md`

**Tópicos:**
- Arquitetura completa
- Fluxo de trabalho detalhado
- Todos os endpoints da API
- Configuração e instalação
- Monitoramento e logs
- Implantação como serviço Windows
- Tratamento de erros
- Performance e segurança
- Manutenção e troubleshooting

## Contato

Sistema SIGA - Gerenciamento de Atendimento INSS
