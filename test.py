import asyncio
import os
import shutil
from audio_separator.separator import Separator
from aiogram import F, Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from shazamio import Shazam

TOKEN = "mykey"
bot = Bot(token=TOKEN)
dp = Dispatcher()
shazam = Shazam()

# Загрузка модели при старте
global_separator = Separator(output_format='WAV')
print("Загрузка модели Kim_Inst.onnx...")
global_separator.load_model('Kim_Inst.onnx')

def prepare_user_directory(user_id: int) -> str:
    user_dir = f"downloads/{user_id}"
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

async def convert_to_voice_ogg(input_p, output_p):
    """Конвертация в OGG Opus для Telegram Voice"""
    process = await asyncio.create_subprocess_exec(
        'ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-i', input_p,
        '-c:a', 'libopus', '-b:a', '64k', '-vbr', 'on',
        output_p, '-y'
    )
    await process.wait()

async def download_from_yt(query, output_mp3):
    """Скачивание трека с YouTube Music"""
    process = await asyncio.create_subprocess_exec(
        'yt-dlp', '--quiet', '--no-warnings',
        '-f', 'bestaudio', '--extract-audio', '--audio-format', 'mp3',
        f"ytsearch1:{query}",
        '-o', output_mp3
    )
    await process.wait()

@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer("Привет, Макс! Отправь аудио, и я найду оригинал (ответ придет голосовым).")

@dp.message(F.audio | F.voice)
async def handle_audio(message: Message):
    user_id = message.from_user.id
    user_dir = prepare_user_directory(user_id)
    audio_obj = message.audio if message.audio else message.voice

    if audio_obj.duration > 25:
        return await message.reply("Максимальная длина — 25 сек.")

    msg = await message.answer("⏳ Анализирую...")
    file_id = audio_obj.file_id
    temp_input = os.path.join(user_dir, f"{file_id}_in.raw")
    temp_wav = os.path.join(user_dir, f"{file_id}.wav")

    try:
        # Скачивание и подготовка для Shazam
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, temp_input)

        # Конвертация для Shazam (44100Hz, Mono)
        await asyncio.create_subprocess_exec(
            'ffmpeg', '-i', temp_input, '-ar', '44100', '-ac', '1', temp_wav, '-y', '-loglevel', 'error'
        )

        out = await shazam.recognize_song(temp_wav)

        # Если не нашли — включаем ИИ
        if not out.get('track'):
            await msg.edit_text("🤖 Работает ИИ: удаление голоса...")
            loop = asyncio.get_event_loop()

            def separate_task():
                global_separator.output_dir = user_dir
                return global_separator.separate(temp_wav)

            output_files = await loop.run_in_executor(None, separate_task)
            inst_path = next((os.path.join(user_dir, f) for f in output_files if 'Instrumental' in f), None)

            if inst_path:
                out = await shazam.recognize_song(inst_path)

        if out.get('track'):
            track = out['track']
            title, artist = track['title'], track['subtitle']

            await msg.edit_text(f"✅ Найдено: {artist} - {title}\nЗагружаю голосовое...")

            raw_audio = os.path.join(user_dir, f"{file_id}_dl.mp3")
            voice_ogg = os.path.join(user_dir, f"{file_id}_voice.ogg")

            await download_from_yt(f"{artist} {title}", raw_audio)

            if os.path.exists(raw_audio):
                await convert_to_voice_ogg(raw_audio, voice_ogg)
                await message.answer_voice(
                    FSInputFile(voice_ogg),
                    caption=f"🎵 {artist} — {title}"
                )
                await msg.delete()
            else:
                await msg.edit_text(f"✅ Найдено: {artist} - {title}\n⚠️ Не удалось скачать файл.")
        else:
            await msg.edit_text("❌ Трек не найден даже после обработки ИИ.")

    except Exception as e:
        print(f"Error: {e}")
        await msg.edit_text("⚠️ Произошла ошибка.")
    finally:
        # Очистка папки пользователя
        shutil.rmtree(user_dir, ignore_errors=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
