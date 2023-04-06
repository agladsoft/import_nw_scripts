import datetime
import json
import os
import sys
import contextlib
import numpy as np
import pandas as pd

input_file_path = os.path.abspath(sys.argv[1])
output_folder = sys.argv[2]

headers_eng = {
    "Год": "year",
    "Месяц": "month",
    "Период": "period",
    "Линия": "line",
    "Порт": "tracking_seaport",
    "Страна": "departure_country",
    "Отправитель": "shipper_name",
    "Получатель": "consignee_name",
    "Экспедитор": "expeditor",
    "Груз": "goods_name",
    "Тип контейнера": "container_type",
    "Размер контейнера": "container_size",
    "Кол-во контейнеров, шт.": "container_count",
    "Терминал": "terminal",
    "TEU": "teu",
    "Номер контейнера": "container_number",
    "КОД ТНВЭД": "tnved",
    "Группа груза по ТНВЭД": "tnved_group_id",
    "Наименование Группы": "tnved_group_name",
    "ИНН": "shipper_inn",
    "УНИ-компания": "shipper_name_unified",
    "Страна КОМПАНИИ": "consignee_country",
    "Направление": "direction",
    "Коносамент": "consignment",
    "Тип парка": "is_empty",
    "Вес нетто (кг)": "goods_weight_netto"
}


def trim_all_columns(df):
    """
    Trim whitespace from ends of each value across all series in dataframe
    """
    trim_strings = lambda x: x.strip() if isinstance(x, str) else x
    return df.applymap(trim_strings)


def convert_to_int(val):
    return int(val) if val.isdigit() else int(val in [True, 'True'])


df = pd.read_csv(input_file_path, dtype=str)
df = df.replace({np.nan: None})
df = df.dropna(axis=0, how='all')
df = df.rename(columns=headers_eng)
df = df.loc[:, ~df.columns.isin(['direction', 'tnved_group_name', 'shipper_inn',
                                 'shipper_name_unified', 'departure_country'])]
df = trim_all_columns(df)
parsed_data = df.to_dict('records')
for dict_data in parsed_data:
    for key, value in dict_data.items():
        with contextlib.suppress(Exception):
            if key in ['year', 'month', 'teu', 'container_size', 'container_count']:
                dict_data[key] = convert_to_int(value)
            elif key in ['tnved_group_id']:
                dict_data[key] = f"{int(value)}"
            elif key in ['goods_weight_netto']:
                dict_data[key] = float(value)
            elif key in ['is_empty']:
                dict_data[key] = value == 'Порожний'

    dict_data['original_file_name'] = os.path.basename(input_file_path)
    dict_data['original_file_parsed_on'] = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
basename = os.path.basename(input_file_path)
output_file_path = os.path.join(output_folder, f'{basename}.json')
with open(f"{output_file_path}", 'w', encoding='utf-8') as f:
    json.dump(parsed_data, f, ensure_ascii=False, indent=4)