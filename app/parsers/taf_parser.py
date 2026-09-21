# app/parsers/taf_parser.py
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

class TafParser:
    def _parse_ddhh_to_datetime(self, ddhh_str: str, reference_datetime: datetime) -> Optional[datetime]:
        """
        Converte uma string DDHH (Dia e Hora) para um objeto datetime,
        usando a data de referência para ano e mês.
        """
        if not ddhh_str or len(ddhh_str) != 4:
            return None

        try:
            day = int(ddhh_str[:2])
            hour = int(ddhh_str[2:])

            """
            A data de referência é o recebimento do TAF, que já está em UTC.
             TAFs podem ter validade que se estende para o dia seguinte ou mais.
             Precisamos ajustar o mês e o ano se o dia do TAF for menor que o dia de referência,
             indicando que a validade se estende para o próximo mês/ano.
            """
            # Começa com o ano e mês da data de referência
            year = reference_datetime.year
            month = reference_datetime.month

            # Tenta criar o datetime no mês atual
            try:
                dt = reference_datetime.replace(day=day, hour=hour, minute=0, second=0, microsecond=0)
            except ValueError: # Dia inválido para o mês atual (31 em fev)
                # Tenta o próximo mês
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                dt = reference_datetime.replace(year=year, month=month, day=day, hour=hour, minute=0, second=0, microsecond=0)
            """
            Ajuste final: se o dia do TAF é menor que o dia de referência,
            e a data resultante é anterior à data de referência,
            então provavelmente é no próximo mês. Ex: ref=28/08, TAF=01/09.
            Se o dia do TAF é menor que o dia de referência, mas a diferença é grande (ex: 28 vs 01),
            e a data de referência está no final do mês, pode ser o próximo mês.
            """
            if dt < reference_datetime - timedelta(days=1): # Permite que seja no dia anterior (TAF de 23Z do dia anterior)
                 month += 1
                 if month > 12:
                     month = 1
                     year += 1
                 dt = reference_datetime.replace(year=year, month=month, day=day, hour=hour, minute=0, second=0, microsecond=0)

            return dt.astimezone(timezone.utc) # Garante que é UTC
        except ValueError:
            return None

    def _parse_section_conditions(self, message_part: str) -> Dict[str, Any]:
        # Extrai condições meteorológicas de uma parte da mensagem TAF.
        conditions = {
            "teto_ft": None,
            "visibilidade_m": None,
            "vento_direcao": None,
            "vento_velocidade_kt": None,
            "cavok": False,
            "vv_presente": False,
        }

        # CAVOK
        if "CAVOK" in message_part:
            conditions["cavok"] = True
            conditions["visibilidade_m"] = 10000 # 10km ou mais
            conditions["teto_ft"] = 99999 # Acima de 25000ft

        # Teto (Vertical Visibility - VV) 
        vv_match = re.search(r'VV(\d{3})', message_part)
        if vv_match:
            conditions["vv_presente"] = True
            conditions["teto_ft"] = int(vv_match.group(1)) * 100

        # Teto (nuvens) 
        if not conditions["cavok"] and not conditions["vv_presente"]:
            cloud_layers = re.findall(r'(BKN|OVC)(\d{3})', message_part)
            lowest_ceiling_ft = None
            for layer_type, height_str in cloud_layers:
                height_ft = int(height_str) * 100
                if lowest_ceiling_ft is None or height_ft < lowest_ceiling_ft:
                    lowest_ceiling_ft = height_ft
            conditions["teto_ft"] = lowest_ceiling_ft

        #  Visibilidade 
        if not conditions["cavok"]:
            vis_match = re.search(r'(?<![\d/])(\d{4})(?![\d/A-Z])', message_part)
            if vis_match:
                visibilidade_str = vis_match.group(1)
                if visibilidade_str == "9999":
                    conditions["visibilidade_m"] = 10000 # 10km ou mais
                else:
                    conditions["visibilidade_m"] = int(visibilidade_str)

        # 5. Vento 
        wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})G?(\d{2,3})?KT', message_part)
        if wind_match:
            conditions["vento_direcao"] = wind_match.group(1)
            conditions["vento_velocidade_kt"] = int(wind_match.group(2))

        return conditions

    def parse(self, taf_message: str, received_at: datetime) -> Dict[str, Any]:
        """
        Parseia uma mensagem TAF completa, dividindo-a em seções de previsão
        e extraindo detalhes para cada seção.
        """
        parsed_data = {
            "mensagem_bruta": taf_message,
            "validade_geral_inicio": None,
            "validade_geral_fim": None,
            "previsoes": []
        }

        # Extrai validade geral do TAF (2912/3018)
        validity_match = re.search(r'(\d{4})/(\d{4})', taf_message)
        if validity_match:
            validity_start_ddhh = validity_match.group(1)
            validity_end_ddhh = validity_match.group(2)

            parsed_data["validade_geral_inicio"] = self._parse_ddhh_to_datetime(validity_start_ddhh, received_at)
            parsed_data["validade_geral_fim"] = self._parse_ddhh_to_datetime(validity_end_ddhh, received_at)

        # Dividir o TAF em seções de previsão
        sections_raw = re.split(r'(BECMG|TEMPO|PROB\d{2})', taf_message)
        # As seções são alternadas: [cabeçalho, tipo_secao1, texto_secao1, tipo_secao2, texto_secao2, ...]
        current_section_type = "BASE"
        current_section_text = sections_raw[0] # Começa com o cabeçalho
        # Encontra o índice da validade geral para saber onde começa a primeira previsão
        validity_start_index = taf_message.find(validity_match.group(0)) if validity_match else -1

        if validity_start_index != -1:
            # A primeira seção "BASE" é o texto após a validade geral e antes da primeira mudança
            base_section_text = taf_message[validity_start_index + len(validity_match.group(0)):].strip()

            # Encontra a primeira ocorrência de BECMG, TEMPO, PROB para delimitar a seção BASE
            first_change_match = re.search(r'(BECMG|TEMPO|PROB\d{2})', base_section_text)
            if first_change_match:
                base_section_text = base_section_text[:first_change_match.start()].strip()

            if base_section_text:
                base_section_data = {
                    "tipo": "BASE",
                    "validade_inicio": parsed_data["validade_geral_inicio"],
                    "validade_fim": parsed_data["validade_geral_fim"],
                    "mensagem_secao_bruta": base_section_text,
                    **self._parse_section_conditions(base_section_text)
                }
                parsed_data["previsoes"].append(base_section_data)

            # Processa as seções de mudança
            remaining_taf = taf_message[validity_start_index + len(validity_match.group(0)):].strip()

            # Dividir o restante do TAF pelas palavras-chave de mudança
            parts = re.split(r'(BECMG|TEMPO|PROB\d{2})', remaining_taf)

            # A primeira parte (parts[0]) é o que já consideramos como BASE.
            # As partes seguintes são tipo_mudanca, texto_mudanca, tipo_mudanca, texto_mudanca...
            for i in range(1, len(parts), 2):
                if i + 1 < len(parts):
                    section_type = parts[i].strip()
                    section_text = parts[i+1].strip()

                    section_validity_match = re.search(r'(\d{4})/(\d{4})', section_text)
                    section_validity_start = None
                    section_validity_end = None

                    if section_validity_match:
                        section_validity_start_ddhh = section_validity_match.group(1)
                        section_validity_end_ddhh = section_validity_match.group(2)
                        section_validity_start = self._parse_ddhh_to_datetime(section_validity_start_ddhh, received_at)
                        section_validity_end = self._parse_ddhh_to_datetime(section_validity_end_ddhh, received_at)

                        # Remove a validade da mensagem bruta da seção para parsing de condições
                        section_text_for_conditions = section_text[section_validity_match.end():].strip()
                    else:
                        section_text_for_conditions = section_text

                    section_data = {
                        "tipo": section_type,
                        "validade_inicio": section_validity_start,
                        "validade_fim": section_validity_end,
                        "mensagem_secao_bruta": section_text, # Mantem a mensagem bruta original da seção
                        **self._parse_section_conditions(section_text_for_conditions)
                    }
                    parsed_data["previsoes"].append(section_data)

        return parsed_data

taf_parser = TafParser()