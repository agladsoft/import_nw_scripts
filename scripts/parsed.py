import re
import os
import sys
import time
import json
import logging
import requests
from typing import Optional
from dotenv import load_dotenv
from clickhouse_connect import get_client
from clickhouse_connect.driver import Client

# LINES = ['СИНОКОР РУС ООО', 'HEUNG-A LINE CO., LTD', 'MSC', 'SINOKOR', 'SINAKOR', 'SKR', 'sinokor',
#          'ARKAS', 'arkas', 'Arkas',
#          'MSC', 'msc', 'Msc', 'SINOKOR', 'sinokor', 'Sinokor', 'SINAKOR', 'sinakor', 'HUENG-A LINE',
#          'HEUNG-A LINE CO., LTD', 'heung']
HEUNG_AND_SINOKOR = ['СИНОКОР РУС ООО', 'HEUNG-A LINE CO., LTD', 'SINOKOR', 'SINAKOR', 'SKR', 'sinokor', 'HUENG-A LINE',
                     'HEUNG-A LINE CO., LTD', 'heung']
IMPORT = ['импорт', 'import']
EXPORT = ['export', 'экспорт']

load_dotenv()


def get_my_env_var(var_name: str) -> str:
    try:
        return os.environ[var_name]
    except KeyError as e:
        raise MissingEnvironmentVariable(f"{var_name} does not exist") from e


class MissingEnvironmentVariable(Exception):
    pass


def clickhouse_client():
    try:
        client: Client = get_client(host=get_my_env_var('HOST'), database=get_my_env_var('DATABASE'),
                                    username=get_my_env_var('USERNAME_DB'), password=get_my_env_var('PASSWORD'))
        logging.info('Connection to ClickHouse is successful')
    except Exception as ex_connect:
        logging.info(f"Error connecting to ClickHouse: {ex_connect}")
        sys.exit(1)
    return client


def uified_list_line_name():
    client = clickhouse_client()
    items = {}
    line_unified_query = client.query(
        f"SELECT * FROM reference_lines where line_unified in ('REEL SHIPPING','SAFETRANS')")
    line_unified = line_unified_query.result_rows
    for data in line_unified:
        key, value = data[1], data[0]
        if key not in items:
            items[key] = [value]
        else:
            items[key].append(value)
    return items


def get_line_unified(item: dict, line_name: str):
    for key, value in item.items():
        if line_name in value:
            return key
    return line_name


LINES = uified_list_line_name()

class ParsedDf:
    def __init__(self, df):
        self.df = df
        self.url = f"http://{os.environ['IP_ADDRESS_CONSIGNMENTS']}:{os.environ['PORT']}"
        self.headers = {
            'Content-Type': 'application/json'
        }

    @staticmethod
    def check_lines(row: dict) -> bool:
        if row.get('line', '').upper() in HEUNG_AND_SINOKOR:
            return False
        return True

    @staticmethod
    def get_direction(direction):
        if direction.lower() in IMPORT:
            return 'import'
        elif direction.lower() in EXPORT:
            return 'export'
        return direction

    @staticmethod
    def get_number_consignment(consignment):
        lst_consignment: list = list(filter(None, re.split(r",|\s", consignment)))
        return lst_consignment[0].strip() if len(lst_consignment) > 1 else consignment

    def body(self, row, consignment):
        consignment_number = self.get_number_consignment(row.get(consignment))
        line_unified = get_line_unified(LINES, row.get('line'))
        return {
            'line': line_unified,
            'consignment': consignment_number,
            'direction': row.get('direction', 'import'),
        }

    def get_port_with_recursion(self, number_attempts: int, row, consignment) -> Optional[str]:
        if number_attempts == 0:
            return None
        try:
            body = self.body(row, consignment)
            body = json.dumps(body)
            response = requests.post(self.url, data=body, headers=self.headers, timeout=120)
            response.raise_for_status()
            return response.json()
        except Exception as ex:
            logging.error(f"Exception is {ex}")
            time.sleep(30)
            number_attempts -= 1
            self.get_port_with_recursion(number_attempts, row, consignment)

    @staticmethod
    def get_consignment(row):
        if row.get('line', '').upper() in ['ARKAS', 'MSC']:
            return 'container_number'
        else:
            if 'booking' in row:
                return 'booking'
            return 'consignment'

    def get_port(self):
        self.add_new_columns()
        logging.info("Запросы к микросервису")
        data = {}
        lines = [name for sublist in list(uified_list_line_name().values()) for name in sublist]
        for index, row in self.df.iterrows():
            if row.get('line', '').upper() not in lines or row.get('tracking_seaport') is not None:
                continue
            if self.check_lines(row) and row.get('goods_name') and \
                    any([i in row.get('goods_name', '').upper() for i in ["ПОРОЖ", "ПРОЖ"]]):
                continue
            consignment = self.get_consignment(row)
            if row.get(consignment, False) not in data:
                data[row.get(consignment)] = {}
                if row.get('enforce_auto_tracking', True):
                    number_attempts = 3
                    port = self.get_port_with_recursion(number_attempts, row, consignment)
                    self.write_port(index, port)
                    try:
                        data[row.get(consignment)].setdefault('tracking_seaport',
                                                              self.df.get('tracking_seaport')[index])
                        data[row.get(consignment)].setdefault('is_auto_tracking',
                                                              self.df.get('is_auto_tracking')[index])
                        data[row.get(consignment)].setdefault('is_auto_tracking_ok',
                                                              self.df.get('is_auto_tracking_ok')[index])
                    except KeyError as ex:
                        logging.info(f'Ошибка при получение ключа из DataFrame {ex}')
            else:
                tracking_seaport = data.get(row.get(consignment)).get('tracking_seaport') if data.get(
                    row.get(consignment)) is not None else None
                is_auto_tracking = data.get(row.get(consignment)).get('is_auto_tracking') if data.get(
                    row.get(consignment)) is not None else None
                is_auto_tracking_ok = data.get(row.get(consignment)).get('is_auto_tracking_ok') if data.get(
                    row.get(consignment)) is not None else None
                self.df.at[index, 'tracking_seaport'] = tracking_seaport
                self.df.at[index, 'is_auto_tracking'] = is_auto_tracking
                self.df.at[index, 'is_auto_tracking_ok'] = is_auto_tracking_ok
        logging.info('Обработка закончена')

    def write_port(self, index, port):
        self.df.at[index, 'is_auto_tracking'] = True
        if port:
            self.df.at[index, 'is_auto_tracking_ok'] = True
            self.df.at[index, 'tracking_seaport'] = port
        else:
            self.df.at[index, 'is_auto_tracking_ok'] = False

    @staticmethod
    def check_line(line):
        if line not in LINES:
            return True
        return False

    def add_new_columns(self):
        if "enforce_auto_tracking" not in self.df.columns:
            self.df['is_auto_tracking'] = None
