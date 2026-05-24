import os
import json


def _final_dedupe(segments_data):
    """Última camada defensiva contra cortes do mesmo tempo: roda
    dedupe_non_overlapping no JSON antes de salvar. Garante que mesmo se
    o pipeline anterior falhar, o arquivo final não conterá duplicatas."""
    if not isinstance(segments_data, dict) or "segments" not in segments_data:
        return segments_data
    segs = segments_data.get("segments", [])
    if not isinstance(segs, list) or len(segs) <= 1:
        return segments_data
    try:
        from scripts.create_viral_segments import dedupe_non_overlapping
    except ImportError:
        try:
            from create_viral_segments import dedupe_non_overlapping
        except ImportError:
            return segments_data
    before = len(segs)
    deduped = dedupe_non_overlapping(segs)
    if len(deduped) != before:
        print(f"[DEDUP-FINAL] {before - len(deduped)} corte(s) removido(s) antes de salvar viral_segments.txt.")
        segments_data = dict(segments_data)
        segments_data["segments"] = deduped
    return segments_data


def save_viral_segments(segments_data=None, project_folder="tmp"):
    output_txt_file = os.path.join(project_folder, "viral_segments.txt")

    # Verifica se o arquivo já existe
    if not os.path.exists(output_txt_file):
        if segments_data is None:
            # Solicita ao usuário que insira o JSON caso o arquivo não exista e os segmentos não estejam definidos
            while True:
                user_input = input("\nPor favor, insira o JSON no formato desejado:\n")
                try:
                    # Tenta carregar o JSON inserido
                    segments_data = json.loads(user_input)

                    # Valida se o formato está correto
                    if "segments" in segments_data and isinstance(segments_data["segments"], list):
                        segments_data = _final_dedupe(segments_data)
                        # Salva os dados em um arquivo JSON
                        with open(output_txt_file, 'w', encoding='utf-8') as file:
                            json.dump(segments_data, file, ensure_ascii=False, indent=4)
                        print(f"Segmentos virais salvos em {output_txt_file}")
                        break
                    else:
                        print("Formato inválido. Certifique-se de que a estrutura está correta.")
                except json.JSONDecodeError:
                    print("Erro ao decifrar o JSON. Por favor, verifique a formatação.")
                print("Por favor, tente novamente.")
        else:
            segments_data = _final_dedupe(segments_data)
            # Caso os segmentos tenham sido gerados, salva automaticamente
            with open(output_txt_file, 'w', encoding='utf-8') as file:
                json.dump(segments_data, file, ensure_ascii=False, indent=4)
            print(f"Segmentos virais salvos em {output_txt_file}\n")
    else:
        print(f"O arquivo {output_txt_file} já existe. Nenhuma entrada adicional é necessária.")