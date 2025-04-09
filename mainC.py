import os
import yaml
import pickle
import logging
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from PIL import Image, ImageTk
import threading
from time import time, sleep
from datetime import datetime, timedelta
import pandas as pd
import requests_cache
import asyncio
import aiohttp
import queue
from ttkthemes import ThemedStyle
from aiocache import cached, Cache  # Para cache assíncrono

# Configurações globais
CONFIG_FILE = 'config.yaml'
CHECKPOINT_FILE = 'fipe_checkpoint.pkl'
logger = logging.getLogger(__name__)

# Configuração do cache para requests (não usado com aiohttp)
requests_cache.install_cache('fipe_cache', expire_after=3600)

def format_currency(value):
    """
    Formata o valor para o padrão brasileiro: R$ 999.999,00
    """
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

class RateLimiter:
    def __init__(self, capacity=5, refill_rate=1):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time()

    async def acquire(self):
        now = time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        sleep_time = (1 - self.tokens) / self.refill_rate
        await asyncio.sleep(sleep_time)
        return await self.acquire()

class FipeSyncCrawler:
    def __init__(self, gui_callback=None):
        self.config = None
        self.rate_limiter = None
        self.processed = set()
        self.current_table = None
        self.gui_callback = gui_callback
        self.load_config()

    def load_config(self):
        with open(CONFIG_FILE, encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        self.headers = {
            'User-Agent': self.config['user_agents'][0],
            **self.config['default_headers']
        }
        self.urls = self.config['api_endpoints']
        self.tipos = self.config['vehicle_types']
        self.combustiveis = self.config['fuel_types']
        self.meses = self.config['month_mapping']
        self.rate_limiter = RateLimiter(
            capacity=self.config.get('rate_limit_capacity', 5),
            refill_rate=self.config.get('rate_limit_refill', 1)
        )
        self.processed = self.load_checkpoint()

    def save_checkpoint(self):
        state = {
            'processed_vehicles': self.processed,
            'current_table': self.current_table,
            'timestamp': datetime.now().isoformat()
        }
        with open(CHECKPOINT_FILE, 'wb') as f:
            pickle.dump(state, f)
        logger.info("Checkpoint salvo com sucesso.")

    def load_checkpoint(self):
        try:
            with open(CHECKPOINT_FILE, 'rb') as f:
                state = pickle.load(f)
                self.current_table = state.get('current_table')
                logger.info(f"Checkpoint carregado. Última atualização: {state.get('timestamp')}")
                return state.get('processed_vehicles', set())
        except (FileNotFoundError, EOFError, KeyError) as e:
            logger.warning(f"Checkpoint não encontrado ou corrompido: {str(e)}")
            return set()

    @cached(ttl=3600, cache=Cache.MEMORY)
    async def http_post(self, session, url_key, params, retry=3):
        for attempt in range(retry + 1):
            try:
                await self.rate_limiter.acquire()
                async with session.post(self.urls[url_key], data=params, headers=self.headers) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 3))
                        logger.warning(f"Rate limit atingido. Tentando novamente em {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    response.raise_for_status()
                    return await response.json()
            except Exception as e:
                logger.error(f"Falha na requisição: {str(e)}")
                if attempt < retry:
                    logger.warning(f"Tentativa {attempt + 1} falhou. Tentando novamente...")
                    await asyncio.sleep(1)
                else:
                    return None

    async def extract_tabelas(self, session):
        tabelas = await self.http_post(session, 'tabelas', {}) or []
        return [
            {
                'id': tbl.get('Codigo'),
                'ano': tbl['Mes'].split('/')[1].strip(),
                'mes_num': self.meses.get(tbl['Mes'].split('/')[0].lower().strip(), '00'),
                'mes_nome': tbl['Mes'].split('/')[0].strip().capitalize()
            }
            for tbl in tabelas if 'Mes' in tbl
        ]

    async def get_marcas(self, session, tabela_id, tipo):
        params = {
            'codigoTabelaReferencia': tabela_id,
            'codigoTipoVeiculo': tipo
        }
        return await self.http_post(session, 'marcas', params) or []

    async def get_modelos(self, session, tabela_id, tipo, marca_id):
        params = {
            'codigoTipoVeiculo': tipo,
            'codigoTabelaReferencia': tabela_id,
            'codigoMarca': marca_id
        }
        response = await self.http_post(session, 'modelos', params)
        return response['Modelos'] if response else []

    async def get_ano_modelos(self, session, tabela_id, tipo, marca_id, modelo_id):
        params = {
            'codigoTipoVeiculo': tipo,
            'codigoTabelaReferencia': tabela_id,
            'codigoMarca': marca_id,
            'codigoModelo': modelo_id
        }
        return await self.http_post(session, 'ano_modelos', params) or []

    async def get_veiculo(self, session, tabela_id, tipo, marca_id, modelo_id, combustivel, ano):
        params = {
            'codigoTipoVeiculo': tipo,
            'codigoTabelaReferencia': tabela_id,
            'codigoMarca': marca_id,
            'codigoModelo': modelo_id,
            'codigoTipoCombustivel': combustivel,
            'anoModelo': ano,
            'tipoVeiculo': self.tipos[tipo],
            'tipoConsulta': 'tradicional'
        }
        return await self.http_post(session, 'veiculo', params)

    def extract_veiculo_data(self, veiculo):
        if not veiculo:
            return None
        try:
            valor = veiculo.get('Valor', 'R$ 0').replace('R$ ', '').replace('.', '').replace(',', '.').strip()
            valor = float(valor) if valor else 0.0
        except ValueError:
            valor = 0.0
        mes_ref = veiculo.get('MesReferencia', '').split()
        mes = self.meses.get(mes_ref[0].lower(), '') if len(mes_ref) > 0 else ''
        ano_ref = mes_ref[2] if len(mes_ref) > 2 else ''
        return {
            'tabela_id': veiculo.get('CodigoTabelaReferencia'),
            'anoref': ano_ref,
            'mesref': mes,
            'tipo': self.tipos.get(veiculo.get('CodigoTipoVeiculo'), 'desconhecido'),
            'fipe_cod': veiculo.get('CodigoFipe'),
            'marca': veiculo.get('Marca', 'N/A'),
            'modelo': veiculo.get('Modelo', 'N/A'),
            'anomod': veiculo.get('AnoModelo', 0),
            'comb_cod': veiculo.get('CodigoTipoCombustivel', 'N/A'),
            'comb_sigla': veiculo.get('SiglaCombustivel', 'N/A'),
            'comb': self.combustiveis.get(veiculo.get('CodigoTipoCombustivel'), 'Desconhecido'),
            'valor': valor,
            'consulta': datetime.now().isoformat()
        }

    async def process_vehicle(self, session, tabela_id, tipo, marca, modelo, ano):
        vehicle_key = f"{tabela_id}-{tipo}-{marca['Value']}-{modelo['Value']}-{ano['Value']}"
        if vehicle_key in self.processed:
            return None
        try:
            cod, combustivel = ano['Value'].split('-')
        except ValueError:
            return None
        veiculo = await self.get_veiculo(session, tabela_id, tipo, marca['Value'], modelo['Value'], combustivel, cod)
        if not veiculo:
            return None
        self.processed.add(vehicle_key)
        if len(self.processed) % 50 == 0:
            self.save_checkpoint()
        data = self.extract_veiculo_data(veiculo)
        if self.gui_callback and data:
            # Registra os dados na tabela e inclui ANOMOD no log
            self.gui_callback('save_vehicle', data)
            ano_mod = "0 KM" if data['anomod'] == 3200 else data['anomod']
            formatted = f"{data['marca']} | {data['modelo']} | {ano_mod}"
            self.gui_callback('update_log', formatted, 'info')
        return data

    async def get_veiculos_por_tabela(self, session, tabela_id, tipos):
        results = []
        for tipo in tipos:
            self.gui_callback('update_log', f"Carregando marcas para o tipo {tipo}...", 'info')
            marcas = await self.get_marcas(session, tabela_id, tipo)
            self.gui_callback('update_log', f"{len(marcas)} marcas carregadas.", 'info')
            for marca in marcas:
                self.gui_callback('update_log', f"Carregando modelos para a marca {marca['Label']}...", 'info')
                modelos = await self.get_modelos(session, tabela_id, tipo, marca['Value'])
                self.gui_callback('update_log', f"{len(modelos)} modelos carregados.", 'info')
                for modelo in modelos:
                    self.gui_callback('update_log', f"Carregando anos para o modelo {modelo['Label']}...", 'info')
                    anos = await self.get_ano_modelos(session, tabela_id, tipo, marca['Value'], modelo['Value'])
                    self.gui_callback('update_log', f"{len(anos)} anos carregados.", 'info')
                    tasks = []
                    for ano in anos:
                        tasks.append(asyncio.create_task(self.process_vehicle(session, tabela_id, tipo, marca, modelo, ano)))
                    results_tasks = await asyncio.gather(*tasks)
                    for res in results_tasks:
                        if res:
                            results.append(res)
        self.gui_callback('update_log', f"Coleta concluída! {len(results)} veículos processados.", 'success')
        return results

class FipeGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.csv_filename = None
        self.excel_filename = None
        self.headers = [
            'tabela_id', 'anoref', 'mesref', 'tipo', 'fipe_cod',
            'marca', 'modelo', 'anomod', 'comb_cod', 'comb_sigla',
            'comb', 'valor', 'consulta'
        ]
        self.title("FIPE Crawler GUI")
        self.geometry("1200x800")
        self.configure(bg='#f0f0f0')
        self.crawler = None
        self.running = False
        self.veiculos = []          # Armazena TODOS os veículos processados
        self.xlsx_saved_count = 0   # Contador para controle do XLSX incremental
        self.log_queue = queue.Queue()  # Fila para logs
        self.start_time = None      # Tempo de início do processamento
        self.veiculos_processados = 0  # Contador de veículos processados
        self.setup_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, lambda: self.update_log("Aplicativo inicializado com sucesso!", 'info'))
        self.after(100, self.process_log_queue)

    def setup_ui(self):
        style = ThemedStyle(self)
        style.set_theme("keramik")
        self.setup_header()
        self.setup_config_section()
        self.setup_progress_section()
        self.setup_log_section()
        self.setup_table_section()
        self.setup_control_buttons()

    def setup_header(self):
        header_frame = ttk.Frame(self)
        header_frame.pack(pady=10, fill='x')
        try:
            img = Image.open('fipe_logo.png').resize((100, 100))
            self.logo = ImageTk.PhotoImage(img)
            ttk.Label(header_frame, image=self.logo).pack(side='left')
        except FileNotFoundError:
            pass
        ttk.Label(header_frame, text="Coletor de Dados FIPE",
                  font=('Helvetica', 16, 'bold'), foreground='#2c3e50').pack(pady=10)

    def setup_config_section(self):
        config_frame = ttk.LabelFrame(self, text="Configurações")
        config_frame.pack(pady=10, padx=20, fill='x')
        ttk.Label(config_frame, text="Ano:").grid(row=0, column=0, padx=5)
        self.ano_combo = ttk.Combobox(config_frame, state='readonly')
        self.ano_combo.grid(row=0, column=1, padx=5)
        self.ano_combo.bind("<<ComboboxSelected>>", self.update_meses)
        ttk.Label(config_frame, text="Mês:").grid(row=0, column=2, padx=5)
        self.mes_combo = ttk.Combobox(config_frame, state='readonly')
        self.mes_combo.grid(row=0, column=3, padx=5)
        ttk.Label(config_frame, text="Tipo de Veículo:").grid(row=0, column=4, padx=5)
        self.tipo_veiculo_combo = ttk.Combobox(
            config_frame, state='readonly',
            values=["1 - Automóveis", "2 - Motocicletas", "3 - Caminhões", "4 - Todos os Veículos"]
        )
        self.tipo_veiculo_combo.grid(row=0, column=5, padx=5)
        self.tipo_veiculo_combo.current(0)
        ttk.Button(config_frame, text="Carregar Tabelas", command=self.load_tables).grid(row=0, column=6, padx=10)

    def setup_progress_section(self):
        progress_frame = ttk.LabelFrame(self, text="Progresso")
        progress_frame.pack(pady=10, padx=20, fill='x')
        self.progress_label = ttk.Label(
            progress_frame,
            text="Veículos processados: 0     Tempo de Execução: 00d 00h 00m 00s     Velocidade de processamento: 0.00 veículos/hora"
        )
        self.progress_label.pack(pady=5)

    def setup_log_section(self):
        log_frame = ttk.LabelFrame(self, text="Logs")
        log_frame.pack(pady=10, padx=20, fill='both', expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.log_area.pack(fill='both', expand=True)

    def setup_table_section(self):
        table_frame = ttk.LabelFrame(self, text="Veículos Processados")
        table_frame.pack(pady=10, padx=20, fill='both', expand=True)
        columns = ("Marca", "Modelo", "AnoMod", "Sigla Combustível", "Valor (em reais)")
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings')
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor='center', width=120)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill='both', expand=True)

    def setup_control_buttons(self):
        control_frame = ttk.Frame(self)
        control_frame.pack(pady=10)
        self.start_btn = ttk.Button(control_frame, text="Iniciar", command=self.start_crawler)
        self.start_btn.pack(side='left', padx=5)
        ttk.Button(control_frame, text="Exportar CSV", command=self.export_csv).pack(side='left', padx=5)
        ttk.Button(control_frame, text="Exportar Excel", command=self.export_excel).pack(side='left', padx=5)
        ttk.Button(control_frame, text="Parar", command=self.stop_crawler).pack(side='left', padx=5)

    def update_meses(self, event=None):
        selected_ano = self.ano_combo.get()
        if not selected_ano:
            return

        async def async_update_meses():
            crawler = FipeSyncCrawler()
            async with aiohttp.ClientSession() as session:
                tables = await crawler.extract_tabelas(session)
                meses = [
                    {'mes_nome': t['mes_nome'], 'mes_num': t['mes_num']}
                    for t in tables if t['ano'] == selected_ano
                ]
                meses_ordenados = sorted(meses, key=lambda x: x['mes_num'])
                meses_nomes = [f"{m['mes_nome']} ({m['mes_num']})" for m in meses_ordenados]
                self.mes_combo['values'] = meses_nomes
                self.update_log(f"Meses carregados para {selected_ano}", 'info')

        asyncio.run(async_update_meses())

    def update_log(self, message, level='info'):
        self.log_queue.put((message, level))

    def process_log_queue(self):
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                tag = level
                color = {
                    'error': 'red',
                    'warning': 'orange',
                    'info': 'black',
                    'success': 'green'
                }.get(level, 'black')
                self.log_area.configure(state='normal')
                self.log_area.insert(tk.END, f"{message}\n", tag)
                self.log_area.tag_config(tag, foreground=color)
                self.log_area.configure(state='disabled')
                self.log_area.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_log_queue)

    def load_tables(self):
        async def async_load_tables():
            crawler = FipeSyncCrawler()
            async with aiohttp.ClientSession() as session:
                self.tables = await crawler.extract_tabelas(session)
                anos = sorted({t['ano'] for t in self.tables}, reverse=True)
                self.ano_combo['values'] = anos
                self.update_log("Tabelas carregadas com sucesso!", 'info')
        asyncio.run(async_load_tables())

    def start_crawler(self):
        if not self.validate_selection():
            return
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # CSV será gerado apenas quando clicado no botão
        self.csv_filename = f"FIPE_{timestamp}.csv"
        # XLSX será salvo incrementalmente a cada 10 veículos
        self.excel_filename = f"FIPE_{timestamp}.xlsx"
        self.selected_table = self.get_selected_table()
        if not self.selected_table:
            messagebox.showerror("Erro", "Nenhuma tabela válida selecionada!")
            return
        self.start_btn['state'] = 'disabled'
        self.update_log("PROCESSAMENTO INICIADO.", 'info')
        self.start_time = datetime.now()
        self.veiculos_processados = 0
        self.xlsx_saved_count = 0
        self.running = True

        tipo_selecionado = self.tipo_veiculo_combo.get()
        if tipo_selecionado == "1 - Automóveis":
            tipos = [1]
        elif tipo_selecionado == "2 - Motocicletas":
            tipos = [2]
        elif tipo_selecionado == "3 - Caminhões":
            tipos = [3]
        elif tipo_selecionado == "4 - Todos os Veículos":
            tipos = [1, 2, 3]
        else:
            tipos = [1]

        threading.Thread(target=self.run_sync, args=(tipos,), daemon=True).start()

    def run_sync(self, tipos):
        async def async_run_sync():
            # Aumenta o limite de conexões para maior paralelismo
            connector = aiohttp.TCPConnector(limit=50)
            crawler = FipeSyncCrawler(self.gui_callback)
            try:
                tabela_id = int(self.selected_table['id'])
                async with aiohttp.ClientSession(connector=connector) as session:
                    self.veiculos = await crawler.get_veiculos_por_tabela(session, tabela_id, tipos)
                    self.update_log(f"Coleta concluída! {len(self.veiculos)} veículos coletados.", 'success')
            except Exception as e:
                self.update_log(f"Erro: {str(e)}", 'error')
            finally:
                self.start_btn.configure(state='normal')
                self.running = False
        asyncio.run(async_run_sync())

    def stop_crawler(self):
        if self.running:
            self.running = False
            self.update_log("Coleta interrompida pelo usuário!", 'warning')

    def validate_selection(self):
        ano = self.ano_combo.get()
        mes = self.mes_combo.get()
        if not ano or not mes:
            messagebox.showerror("Erro", "Selecione um ano e mês válidos!")
            return False
        return True

    def export_csv(self):
        # Gera o CSV com todos os dados acumulados somente quando o botão é clicado.
        if not self.veiculos:
            messagebox.showwarning("Aviso", "Nenhum dado para exportar!")
            return
        df = pd.DataFrame(self.veiculos)
        df.to_csv(self.csv_filename, index=False)
        self.update_log(f"Dados exportados para {self.csv_filename}", 'success')

    def export_excel(self):
        # O XLSX já é salvo incrementalmente.
        if not os.path.exists(self.excel_filename):
            messagebox.showwarning("Aviso", "Nenhum dado salvo no XLSX ainda!")
            return
        df = pd.read_excel(self.excel_filename)
        df.to_excel(self.excel_filename, index=False)
        self.update_log(f"Dados exportados para {self.excel_filename}", 'success')

    def gui_callback(self, action, *args):
        if action == 'update_log':
            self.update_log(*args)
        elif action == 'save_vehicle':
            self.save_vehicle_data(args[0])
        elif action == 'update_current_vehicle':
            self.update_current_vehicle(*args)

    def save_vehicle_data(self, data):
        try:
            self.veiculos.append(data)
            self.veiculos_processados += 1

            # Insere os dados na Treeview (sem "anoref")
            ano_mod = "0 KM" if data['anomod'] == 3200 else data['anomod']
            valor_formatado = format_currency(data['valor'])
            self.tree.insert('', 'end', values=(
                data['marca'], data['modelo'], ano_mod, data['comb_sigla'], valor_formatado
            ))
            # Auto-scroll: mostra sempre a última linha
            children = self.tree.get_children()
            if children:
                self.tree.see(children[-1])

            # Salva incrementalmente o XLSX a cada 10 veículos novos (sem limpar self.veiculos)
            if (len(self.veiculos) - self.xlsx_saved_count) >= 10:
                new_batch = self.veiculos[self.xlsx_saved_count:]
                try:
                    if not os.path.exists(self.excel_filename):
                        pd.DataFrame(new_batch).to_excel(self.excel_filename, index=False)
                    else:
                        df_existente = pd.read_excel(self.excel_filename)
                        df_new = pd.DataFrame(new_batch)
                        df_completo = pd.concat([df_existente, df_new], ignore_index=True)
                        df_completo.to_excel(self.excel_filename, index=False)
                    self.xlsx_saved_count = len(self.veiculos)
                    self.update_log("Lote de 10 veículos gravado no XLSX com sucesso.", 'success')
                except Exception as e:
                    self.update_log(f"Erro ao salvar XLSX: {str(e)}", 'error')
        except Exception as e:
            self.update_log(f"Erro ao salvar dados: {str(e)}", 'error')

    def on_close(self):
        if self.running:
            if messagebox.askokcancel("Sair", "A coleta está em andamento. Deseja realmente sair?"):
                self.stop_crawler()
                self.destroy()
        else:
            self.destroy()

    def get_selected_table(self):
        selected_ano = self.ano_combo.get()
        selected_mes = self.mes_combo.get().split(' ')[0]
        if not selected_ano or not selected_mes:
            return None
        for table in self.tables:
            if table['ano'] == selected_ano and table['mes_nome'].lower() == selected_mes.lower():
                return table
        return None

    def update_tempo_execucao(self):
        if self.start_time:
            tempo_decorrido = datetime.now() - self.start_time
            dias = tempo_decorrido.days
            horas, resto = divmod(tempo_decorrido.seconds, 3600)
            minutos, segundos = divmod(resto, 60)
            if self.veiculos_processados > 0:
                tempo_total_seg = tempo_decorrido.total_seconds()
                velocidade = (self.veiculos_processados / tempo_total_seg) * 3600
            else:
                velocidade = 0.0
            self.progress_label['text'] = (
                f"Veículos processados: {self.veiculos_processados:,.0f}     "
                f"Tempo de Execução: {dias:02d}d {horas:02d}h {minutos:02d}m {segundos:02d}s     "
                f"Velocidade de processamento: {velocidade:.2f} veículos/hora"
            )
        self.after(1000, self.update_tempo_execucao)

if __name__ == "__main__":
    app = FipeGUI()
    app.after(1000, app.update_tempo_execucao)
    app.mainloop()
