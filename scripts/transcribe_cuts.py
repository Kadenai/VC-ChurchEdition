import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def transcribe(project_folder="tmp"):
    def generate_whisperx(input_file, output_folder, model='large-v3'):
        output_file = os.path.join(output_folder, f"{os.path.splitext(os.path.basename(input_file))[0]}.srt")
        json_file = os.path.join(output_folder, f"{os.path.splitext(os.path.basename(input_file))[0]}.json")

        if os.path.exists(json_file) and os.path.exists(output_file):
            print(f"Arquivos já existem, pulando: {json_file} | {output_file}")
            return

        base_cmd = [
            "whisperx",
            input_file,
            "--model", model,
            "--task", "transcribe",
            "--align_model", "WAV2VEC2_ASR_LARGE_LV60K_960H",
            "--chunk_size", "10",
            "--vad_onset", "0.4",
            "--vad_offset", "0.3",
            "--compute_type", "float32",
            "--batch_size", "10",
            "--output_dir", output_folder,
        ]

        formats_to_generate = []
        if not os.path.exists(json_file):
            formats_to_generate.append("json")
        if not os.path.exists(output_file):
            formats_to_generate.append("srt")

        if not formats_to_generate:
            print(f"Arquivos já existem, pulando: {json_file} | {output_file}")
            return

        print(f"Transcrevendo: {input_file}...")
        for out_fmt in formats_to_generate:
            command = base_cmd + ["--output_format", out_fmt]
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode != 0:
                print(f"Erro durante a transcrição ({out_fmt}):")
                print(result.stderr or result.stdout)
                return

        print(f"Transcrição concluída. Arquivo salvo em: {output_file} e {json_file}")

    # Define o diretório de entrada e o diretório de saída
    input_folder = os.path.join(project_folder, 'final')
    output_folder = os.path.join(project_folder, 'subs')
    os.makedirs(output_folder, exist_ok=True)

    if not os.path.exists(input_folder):
        print(f"Pasta de entrada não encontrada: {input_folder}")
        return

    # Itera sobre todos os arquivos na pasta de entrada
    for filename in os.listdir(input_folder):
        if filename.endswith('.mp4'):  # Filtra apenas arquivos .mp4
            input_file = os.path.join(input_folder, filename)
            generate_whisperx(input_file, output_folder)

