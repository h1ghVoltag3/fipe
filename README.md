# fipe
 FIPE Crawler - Coletor de Dados da Tabela FIPE 

FIPE Crawler GUI
License
Python Version

O FIPE Crawler GUI é uma interface gráfica desenvolvida em Python para coletar dados de veículos da Tabela FIPE (Fundação Instituto de Pesquisas Econômicas). O programa permite baixar informações detalhadas sobre marcas, modelos, anos e valores de veículos, salvando os dados em formatos CSV e Excel.

Índice
Recursos Principais
Instalação
Uso
Estrutura do Projeto
Configuração
Contribuição
Licença
Recursos Principais
Interface Gráfica Amigável : Desenvolvido com tkinter, oferece uma interface intuitiva para configuração e execução.
Coleta Automática de Dados : Coleta informações de veículos diretamente da API da Tabela FIPE.
Exportação de Dados : Exporta os dados coletados em formatos CSV e Excel.
Barras de Progresso Dinâmicas : Exibe o progresso em tempo real durante a coleta de dados.
Checkpoint System : Salva periodicamente o estado da coleta para evitar perda de dados.
Rate Limiter : Implementa um limitador de taxa para evitar bloqueios por excesso de requisições.
Instalação
Pré-requisitos
Python 3.8 ou superior
Dependências instaladas via pip
Passos para Instalação
Clone este repositório:
bash
Copy
1
2
git clone https://github.com/seu-usuario/fipe-crawler-gui.git
cd fipe-crawler-gui
Instale as dependências:
bash
Copy
1
pip install -r requirements.txt
Configure o arquivo config.yaml conforme necessário (consulte a seção Configuração ).
Uso
Executando o Programa
Execute o programa com o seguinte comando:

bash
Copy
1
python main.py
Fluxo de Trabalho
Selecione o Ano e Mês :
No menu "Configurações", escolha o ano e o mês desejados.
Clique em "Carregar Tabelas" para carregar as tabelas disponíveis para o período selecionado.
Inicie a Coleta :
Clique no botão "Iniciar" para começar a coleta de dados.
As barras de progresso exibirão o status da coleta em tempo real.
Exporte os Dados :
Após a conclusão da coleta, clique em "Exportar CSV" ou "Exportar Excel" para salvar os dados.
Estrutura do Projeto
Copy
1
2
3
4
5
6
fipe-crawler-gui/
├── config.yaml          # Arquivo de configuração com endpoints e parâmetros da API
├── main.py              # Código principal da aplicação
├── requirements.txt     # Lista de dependências do projeto
├── README.md            # Documentação do projeto
└── fipe_logo.png        # Logo opcional para a interface gráfica
Configuração
O arquivo config.yaml contém as configurações necessárias para o funcionamento do programa. Abaixo está um exemplo de configuração:

yaml
Copy
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
⌄
⌄
⌄
⌄
⌄
⌄
user_agents:
  - "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

default_headers:
  Accept: "application/json"
  Content-Type: "application/x-www-form-urlencoded"

api_endpoints:
  tabelas: "https://api.fipe.org/tabelas"
  marcas: "https://api.fipe.org/marcas"
  modelos: "https://api.fipe.org/modelos"
  ano_modelos: "https://api.fipe.org/ano_modelos"
  veiculo: "https://api.fipe.org/veiculo"

vehicle_types:
  1: "Carro"
  3: "Moto"

fuel_types:
  1: "Gasolina"
  2: "Álcool"
  3: "Diesel"

month_mapping:
  janeiro: "01"
  fevereiro: "02"
  março: "03"
  abril: "04"
  maio: "05"
  junho: "06"
  julho: "07"
  agosto: "08"
  setembro: "09"
  outubro: "10"
  novembro: "11"
  dezembro: "12"

rate_limit_capacity: 5
rate_limit_refill: 1
timeout: 20
Certifique-se de que os endpoints e parâmetros estejam corretos antes de executar o programa.

Contribuição
Contribuições são bem-vindas! Para contribuir:

Faça um fork deste repositório.
Crie uma branch para sua feature ou correção:
bash
Copy
1
git checkout -b feature/nome-da-feature
Faça suas alterações e envie um pull request.
Por favor, siga as diretrizes de estilo e documentação ao enviar suas contribuições.

Licença
Este projeto está licenciado sob a MIT License . Consulte o arquivo LICENSE para mais detalhes.

Créditos
API FIPE : Dados fornecidos pela Fundação Instituto de Pesquisas Econômicas.
Bibliotecas Python Utilizadas :
tkinter: Interface gráfica.
pandas: Manipulação de dados.
requests: Requisições HTTP.
yaml: Leitura do arquivo de configuração.

Se você tiver dúvidas ou sugestões, sinta-se à vontade para abrir uma issue no repositório. 
