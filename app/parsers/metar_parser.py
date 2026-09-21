# app/parsers/metar_parser.py
import re


class MetarParser:

    def parse(self, metar_message: str) -> dict:
        parsed_data = {
            "mensagem_bruta": metar_message,
            "teto_ft": None, # Pode ser None se não houver teto definido
            "visibilidade_m": None,
            "vento_direcao": None,
            "vento_velocidade_kt": None,
            "temperatura_c": None,
            "ponto_orvalho_c": None,
            "pressao_hpa": None,
            "cavok": False,
            "vv_presente": False,
        }

        # Verifica CAVOK 
        if "CAVOK" in metar_message:
            parsed_data["cavok"] = True
            parsed_data["visibilidade_m"] = 10000 # 10km ou mais
            parsed_data["teto_ft"] = 99999 # Teto ilimitado (ou acima de 5000ft)
            # Se CAVOK, não precisamos procurar por visibilidade e teto
            # Mas ainda podemos procurar por vento, temperatura, etc.

        # Teto (Vertical Visibility - VV)
        vv_match = re.search(r'VV(\d{3})', metar_message)
        if vv_match:
            parsed_data["vv_presente"] = True
            parsed_data["teto_ft"] = int(vv_match.group(1)) * 100 # Teto em pés
            # Se VV presente, ele define o teto, não precisamos de nuvens para teto.

        # Teto (nuvens)
        # Só procura por nuvens se VV não estiver presente e CAVOK não estiver ativo.
        if not parsed_data["cavok"] and not parsed_data["vv_presente"]:
            cloud_layers = re.findall(r'(BKN|OVC)(\d{3})', metar_message) # Apenas BKN e OVC
            lowest_ceiling_ft = None
            for layer_type, height_str in cloud_layers:
                height_ft = int(height_str) * 100
                if lowest_ceiling_ft is None or height_ft < lowest_ceiling_ft:
                    lowest_ceiling_ft = height_ft
            parsed_data["teto_ft"] = lowest_ceiling_ft
            # Se não encontrou BKN/OVC, teto_ft permanece None, o que é correto para FEW/SCT ou céu claro.

        # Visibilidade 
        # Só procura por visibilidade se CAVOK não estiver ativo.
        if not parsed_data["cavok"]:
            vis_match = re.search(r'\s(\d{4})\s(?!NDV)', metar_message)
            if vis_match:
                visibilidade_str = vis_match.group(1)
                if visibilidade_str == "9999":
                    parsed_data["visibilidade_m"] = 10000 # 10km ou mais
                else:
                    parsed_data["visibilidade_m"] = int(visibilidade_str)

        # Vento
        wind_match = re.search(r'(\d{3}|VRB)(\d{2,3})G?(\d{2,3})?KT', metar_message)
        if wind_match:
            parsed_data["vento_direcao"] = wind_match.group(1)
            parsed_data["vento_velocidade_kt"] = int(wind_match.group(2))

        # Temperatura e ponto de orvalho
        temp_match = re.search(r'(?<![\d/])(M?\d{2})/(M?\d{2}|/{2})(?!\d)', metar_message)
        if temp_match:
            parsed_data["temperatura_c"] = int(temp_match.group(1).replace('M', '-'))
            orvalho = temp_match.group(2)
            if orvalho != "//":
                parsed_data["ponto_orvalho_c"] = int(orvalho.replace('M', '-'))

        # Pressão (QNH) 
        qnh_match = re.search(r'Q(\d{4})', metar_message)
        if qnh_match:
            parsed_data["pressao_hpa"] = int(qnh_match.group(1))

        return parsed_data

metar_parser = MetarParser()