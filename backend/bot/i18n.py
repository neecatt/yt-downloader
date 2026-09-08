from __future__ import annotations

from typing import Any

SUPPORTED_LANGUAGES = ("en", "ru", "az")
LANGUAGE_NAMES = {"en": "🇬🇧 English", "ru": "🇷🇺 Русский", "az": "🇦🇿 Azərbaycan dili"}

_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "welcome": "👋 Welcome!\n\nDownload videos and get AI-powered transcriptions & summaries — directly in Telegram.\n\n🔗 Just send me a link from YouTube, TikTok, Instagram, or another supported platform.\n\nI can help you:\n\n📥 Download videos\n📝 Transcribe audio/video\n✨ Summarize content with AI\n🌍 Translate transcripts\n\nNo complicated setup — just paste a link to get started.",
        "support": "If this bot saves you time, you can support its hosting costs.\n\nDonations are completely optional, and the bot remains free for everyone. ☕",
        "support_unconfigured": "Support is not configured yet, but the bot remains free to use.",
        "feedback_usage": "Thanks for helping improve the bot! Send your feedback like this:\n\n/feedback Your message here",
        "feedback_saved": "Thanks for helping improve the bot! Your feedback has been saved.",
        "feedback_failed": "I couldn’t save that feedback right now. Please try again later.",
        "feedback_too_long": "Please keep feedback under 4096 characters.",
        "support_button": "☕ Support this bot",
        "choice_telegram": "📨 Send through Telegram",
        "choice_link": "⬇️ Give me a download link",
        "language_saved": "Language updated.", "settings_language": "🌐 Choose your language:", "duration": "Duration", "video_only": "This is an image or carousel post. This bot only downloads videos and audio. Please send an individual video link.", "download_file": "⬇️ Download file",
        "invalid_link": "Please send a YouTube, TikTok, Instagram, Facebook, X, or LinkedIn HTTPS link.",
        "download_usage": "Usage: /download <https-url>",
        "download_url": "Please provide one valid HTTPS video URL.",
        "analysis_limit": "You have reached the hourly link-analysis limit. Please try again later.",
        "analyzing": "🔎 Analyzing the link…",
        "checking": "🔎 Checking the link…",
        "choose_format": "🎬 {title}{duration}\n\nChoose a format:",
        "fast_360": "360p · fast", "quality_480": "480p", "quality_720": "720p", "quality_1080": "1080p", "recommended_720": "▶️ 720p · recommended", "video_options": "🎞 Other video", "audio_options": "🎧 Other MP3", "back_to_formats": "‹ Back", "choose_video_quality": "🎞 Choose video quality:", "choose_audio_quality": "🎧 Choose MP3 quality:",
        "best": "Best quality", "mp3_128": "MP3 · 128 kbps", "mp3_192": "MP3 · 192 kbps", "mp3_320": "MP3 · 320 kbps",
        "ready_choice": "✅ Ready: {title}\nSize: {size:.1f} MB\n\nHow would you like to receive it?",
        "link_unconfigured": "Download links are not configured. Please choose Telegram delivery instead.",
        "delivery_expired": "That delivery choice has expired. Please send the link again.",
        "upload_telegram": "⬆️ Uploading to Telegram…\nDownload: 100%",
        "prepare_link": "☁️ Preparing your download link…",
        "telegram_failed_other": "Telegram could not accept the file. Please try the other delivery option.",
        "telegram_failed_quality": "Telegram could not accept the file. Try a lower quality.",
        "downloading": "⬇️ Downloading {fmt}…",
        "upload_cloud": "☁️ Uploading to cloud storage…\nDownload: 100%",
        "already_running": "A download is already running in this chat. Please wait for it to finish.",
        "download_limit": "You have reached the download limit. Please try again later.",
        "invalid_button": "That button is no longer valid. Please send the link again.",
        "link_expired": "That link has expired. Please send it again.",
        "ready_link_choice": "You chose a temporary download link.",
        "ready_link_large": "The media exceeds Telegram's upload limit, so I’m giving you a temporary download link instead.",
    },
    "ru": {
        "welcome": "👋 Добро пожаловать!\n\nСкачивайте видео и получайте расшифровки и краткие содержания с помощью ИИ — прямо в Telegram.\n\n🔗 Просто отправьте ссылку с YouTube, TikTok, Instagram или другой поддерживаемой платформы.\n\nЯ умею:\n\n📥 Скачивать видео\n📝 Расшифровывать аудио и видео\n✨ Делать краткие содержания с помощью ИИ\n🌍 Переводить расшифровки\n\nНикаких сложных настроек — просто отправьте ссылку.",
        "support": "Если бот экономит ваше время, вы можете поддержать расходы на его хостинг.\n\nПожертвования полностью добровольны, бот остаётся бесплатным для всех. ☕",
        "support_unconfigured": "Поддержка пока не настроена, но бот остаётся бесплатным.",
        "feedback_usage": "Спасибо, что помогаете улучшать бота! Отправьте отзыв так:\n\n/feedback Ваше сообщение",
        "feedback_saved": "Спасибо! Ваш отзыв сохранён.",
        "feedback_failed": "Не удалось сохранить отзыв. Попробуйте позже.",
        "feedback_too_long": "Пожалуйста, ограничьте отзыв 4096 символами.",
        "support_button": "☕ Поддержать бота",
        "choice_telegram": "📨 Отправить в Telegram", "choice_link": "⬇️ Получить ссылку",
        "language_saved": "Язык обновлён.", "settings_language": "🌐 Выберите язык:", "duration": "Длительность", "video_only": "Это публикация с изображением или каруселью. Бот скачивает только видео и аудио. Отправьте ссылку на отдельное видео.", "download_file": "⬇️ Скачать файл", "invalid_link": "Отправьте HTTPS-ссылку на YouTube, TikTok, Instagram, Facebook, X или LinkedIn.",
        "download_usage": "Использование: /download <https-ссылка>", "download_url": "Укажите одну корректную HTTPS-ссылку на видео.",
        "analysis_limit": "Вы достигли часового лимита анализа ссылок. Попробуйте позже.", "analyzing": "🔎 Анализирую ссылку…", "checking": "🔎 Проверяю ссылку…",
        "choose_format": "🎬 {title}{duration}\n\nВыберите формат:", "fast_360": "360p · быстро", "quality_480": "480p", "quality_720": "720p", "quality_1080": "1080p", "recommended_720": "▶️ 720p · рекомендуется", "video_options": "🎞 Другое видео", "audio_options": "🎧 Другой MP3", "back_to_formats": "‹ Назад", "choose_video_quality": "🎞 Выберите качество видео:", "choose_audio_quality": "🎧 Выберите качество MP3:", "best": "Лучшее качество", "mp3_128": "MP3 · 128 кбит/с", "mp3_192": "MP3 · 192 кбит/с", "mp3_320": "MP3 · 320 кбит/с",
        "ready_choice": "✅ Готово: {title}\nРазмер: {size:.1f} МБ\n\nКак отправить файл?", "link_unconfigured": "Ссылки для скачивания не настроены. Выберите отправку в Telegram.", "delivery_expired": "Выбор доставки истёк. Отправьте ссылку ещё раз.", "upload_telegram": "⬆️ Отправляю в Telegram…\nЗагрузка: 100%", "prepare_link": "☁️ Подготавливаю ссылку…", "telegram_failed_other": "Telegram не смог принять файл. Попробуйте другой способ доставки.", "telegram_failed_quality": "Telegram не смог принять файл. Попробуйте более низкое качество.", "downloading": "⬇️ Загружаю {fmt}…", "upload_cloud": "☁️ Загружаю в облачное хранилище…\nЗагрузка: 100%", "already_running": "В этом чате уже выполняется загрузка. Подождите.", "download_limit": "Вы достигли лимита загрузок. Попробуйте позже.", "invalid_button": "Эта кнопка больше недействительна. Отправьте ссылку ещё раз.", "link_expired": "Срок действия ссылки истёк. Отправьте её ещё раз.", "ready_link_choice": "Вы выбрали временную ссылку для скачивания.", "ready_link_large": "Файл превышает лимит Telegram, поэтому я выдаю временную ссылку для скачивания.",
    },
    "az": {
        "welcome": "👋 Xoş gəlmisiniz!\n\nVideoları yükləyin və AI ilə transkripsiya və xülasələr əldə edin — birbaşa Telegram-da.\n\n🔗 Sadəcə YouTube, TikTok, Instagram və ya dəstəklənən başqa platformadan link göndərin.\n\nSizə kömək edə bilərəm:\n\n📥 Videoları yükləmək\n📝 Audio/videonu transkripsiya etmək\n✨ AI ilə məzmunu xülasə etmək\n🌍 Transkripsiyaları tərcümə etmək\n\nMürəkkəb quraşdırma lazım deyil — başlamaq üçün linki göndərin.",
        "support": "Bu bot vaxtınıza qənaət edirsə, hosting xərclərini dəstəkləyə bilərsiniz.\n\nİanələr tamamilə könüllüdür və bot hər kəs üçün pulsuz olaraq qalır. ☕",
        "support_unconfigured": "Dəstək hələ konfiqurasiya edilməyib, lakin bot pulsuz olaraq qalır.",
        "feedback_usage": "Botu yaxşılaşdırmağa kömək etdiyiniz üçün təşəkkürlər! Rəyinizi belə göndərin:\n\n/feedback Rəyiniz burada",
        "feedback_saved": "Təşəkkürlər! Rəyiniz yadda saxlanıldı.", "feedback_failed": "Rəyi indi yadda saxlamaq mümkün olmadı. Sonra yenidən cəhd edin.", "feedback_too_long": "Rəyinizi 4096 simvoldan qısa saxlayın.", "support_button": "☕ Bota dəstək ol", "choice_telegram": "📨 Telegram ilə göndər", "choice_link": "⬇️ Yükləmə linki ver", "language_saved": "Dil yeniləndi.", "invalid_link": "YouTube, TikTok, Instagram, Facebook, X və ya LinkedIn HTTPS video linki göndərin.", "download_usage": "İstifadə: /download <https-link>", "download_url": "Bir düzgün HTTPS video linki göndərin.", "analysis_limit": "Saatlıq link analiz limitinə çatmısınız. Sonra yenidən cəhd edin.", "analyzing": "🔎 Link analiz edilir…", "checking": "🔎 Link yoxlanılır…", "choose_format": "🎬 {title}{duration}\n\nFormat seçin:", "fast_360": "360p · sürətli", "quality_480": "480p", "quality_720": "720p", "quality_1080": "1080p", "best": "Ən yaxşı keyfiyyət", "mp3_128": "MP3 · 128 kbit/s", "mp3_192": "MP3 · 192 kbit/s", "mp3_320": "MP3 · 320 kbit/s", "ready_choice": "✅ Hazırdır: {title}\nÖlçü: {size:.1f} MB\n\nNecə almaq istəyirsiniz?", "link_unconfigured": "Yükləmə linkləri konfiqurasiya edilməyib. Telegram ilə göndərilməni seçin.", "delivery_expired": "Çatdırılma seçiminin vaxtı bitib. Linki yenidən göndərin.", "upload_telegram": "⬆️ Telegram-a yüklənir…\nYükləmə: 100%", "prepare_link": "☁️ Yükləmə linki hazırlanır…", "telegram_failed_other": "Telegram faylı qəbul etmədi. Digər çatdırılma üsulunu sınayın.", "telegram_failed_quality": "Telegram faylı qəbul etmədi. Daha aşağı keyfiyyət seçin.", "downloading": "⬇️ {fmt} yüklənir…", "upload_cloud": "☁️ Bulud yaddaşına yüklənir…\nYükləmə: 100%", "already_running": "Bu çatda artıq yükləmə gedir. Gözləyin.", "download_limit": "Yükləmə limitinə çatmısınız. Sonra yenidən cəhd edin.", "invalid_button": "Bu düymə artıq keçərli deyil. Linki yenidən göndərin.", "link_expired": "Linkin vaxtı bitib. Onu yenidən göndərin.", "ready_link_choice": "Müvəqqəti yükləmə linkini seçdiniz.", "ready_link_large": "Fayl Telegram limitini keçir, ona görə müvəqqəti yükləmə linki verirəm.",
    },
}

_TEXT["az"].update({
    "settings_language": "🌐 Dilinizi seçin:",
    "duration": "Müddət",
    "video_only": "Bu, şəkil və ya karusel paylaşımıdır. Bot yalnız video və audio yükləyir. Ayrı video linki göndərin.",
    "download_file": "⬇️ Faylı yüklə",
    "recommended_720": "▶️ 720p · tövsiyə edilir",
    "video_options": "🎞 Digər video",
    "audio_options": "🎧 Digər MP3",
    "back_to_formats": "‹ Geri",
    "choose_video_quality": "🎞 Video keyfiyyətini seçin:",
    "choose_audio_quality": "🎧 MP3 keyfiyyətini seçin:",
})

_TEXT["en"].update({"format_label": "Format", "size_label": "Size"})
_TEXT["en"].update({"progress_finished": "🧩 Download complete. Merging/converting…", "progress_started": "🧩 Preparing media…", "progress_processing": "🧩 Processing media…", "progress_downloading": "⬇️ Downloading {fmt}…", "private_error": "This media is private or requires login. The bot can only access publicly available posts and accounts.", "age_error": "This video is age-restricted and cannot be downloaded here.", "geo_error": "This video is unavailable in the downloader's region.", "access_error": "YouTube requires an access check. Configure a JavaScript runtime, cookies, or a PO token, then try again.", "unavailable_error": "YouTube reports that this video is unavailable or no longer public.", "forbidden_error": "The source rejected this server's request. Try configuring cookies or a proxy.", "format_error": "That quality is not available for this video. Try another quality.", "size_error": "The file is too large. Please choose a lower quality or MP3.", "network_error": "The source timed out. Please try again in a moment.", "generic_error": "I couldn't download that video. Please check the link and try again."})
_TEXT["ru"].update({"progress_finished": "🧩 Загрузка завершена. Объединяю/конвертирую…", "progress_started": "🧩 Подготавливаю медиа…", "progress_processing": "🧩 Обрабатываю медиа…", "progress_downloading": "⬇️ Загружаю {fmt}…", "private_error": "Это приватный материал или требуется вход. Бот работает только с публичными публикациями и аккаунтами.", "age_error": "Это видео ограничено по возрасту и не может быть скачано.", "geo_error": "Видео недоступно в регионе загрузчика.", "access_error": "YouTube требует проверку доступа. Настройте JavaScript, cookies или PO-токен и повторите попытку.", "unavailable_error": "YouTube сообщает, что видео недоступно или больше не является публичным.", "forbidden_error": "Источник отклонил запрос сервера. Попробуйте настроить cookies или прокси.", "format_error": "Это качество недоступно. Попробуйте другое качество.", "size_error": "Файл слишком большой. Выберите более низкое качество или MP3.", "network_error": "Источник не ответил вовремя. Попробуйте ещё раз.", "generic_error": "Не удалось скачать видео. Проверьте ссылку и попробуйте снова."})
_TEXT["az"].update({"progress_finished": "🧩 Yükləmə tamamlandı. Birləşdirilir/çevirilir…", "progress_started": "🧩 Media hazırlanır…", "progress_processing": "🧩 Media emal edilir…", "progress_downloading": "⬇️ {fmt} yüklənir…", "private_error": "Bu media şəxsidir və ya giriş tələb edir. Bot yalnız ictimai paylaşımlara və hesablara daxil ola bilər.", "age_error": "Bu video yaş məhdudiyyətlidir və yüklənə bilməz.", "geo_error": "Video yükləyicinin regionunda əlçatan deyil.", "access_error": "YouTube giriş yoxlaması tələb edir. JavaScript, cookies və ya PO tokeni konfiqurasiya edin.", "unavailable_error": "YouTube videonun əlçatmaz və ya artıq ictimai olmadığını bildirir.", "forbidden_error": "Mənbə server sorğusunu rədd etdi. Cookies və ya proxy konfiqurasiya edin.", "format_error": "Bu keyfiyyət mövcud deyil. Başqa keyfiyyət sınayın.", "size_error": "Fayl çox böyükdür. Daha aşağı keyfiyyət və ya MP3 seçin.", "network_error": "Mənbə vaxtında cavab vermədi. Bir az sonra yenidən cəhd edin.", "generic_error": "Videonu yükləmək mümkün olmadı. Linki yoxlayın və yenidən cəhd edin."})
_TEXT["ru"].update({"format_label": "Формат", "size_label": "Размер"})
_TEXT["az"].update({"format_label": "Format", "size_label": "Ölçü"})
_TEXT["en"]["settings_hint"] = "Use /settings to change the language later."
_TEXT["ru"]["settings_hint"] = "Используйте /settings, чтобы позже изменить язык."
_TEXT["az"]["settings_hint"] = "Dili sonra dəyişmək üçün /settings əmrindən istifadə edin."
_TEXT["en"]["help_hint"] = "Use /help for full instructions."
_TEXT["ru"]["help_hint"] = "Используйте /help для полной инструкции."
_TEXT["az"]["help_hint"] = "Tam izah üçün /help əmrindən istifadə edin."
_TEXT["en"]["help"] = "🎬 How to use this bot\n\n1. Send a public video link from YouTube, TikTok, Instagram, Facebook, X, or LinkedIn.\n2. Choose a video quality or MP3 bitrate.\n3. For files within Telegram’s limit, choose Telegram delivery or a temporary download link. Larger files automatically use a temporary link.\n\nSupported choices:\n• Video: 360p, 480p, 720p, 1080p, or best quality\n• Audio: MP3 at 128, 192, or 320 kbps\n\nOnly public video posts are supported. Private accounts, login-protected content, image posts, photo posts, and carousels are not supported.\n\nCommands:\n/start — Show the welcome screen\n/help — Show this guide\n/download <link> — Start a download\n/feedback <text> — Send feedback\n/support — Support the bot\n/settings — Change language"
_TEXT["ru"]["help"] = "🎬 Как пользоваться ботом\n\n1. Отправьте публичную ссылку с YouTube, TikTok, Instagram, Facebook, X или LinkedIn.\n2. Выберите качество видео или битрейт MP3.\n3. Для файлов в пределах лимита Telegram выберите отправку в Telegram или временную ссылку. Большие файлы автоматически получают временную ссылку.\n\nДоступные варианты:\n• Видео: 360p, 480p, 720p, 1080p или лучшее качество\n• Аудио: MP3 128, 192 или 320 кбит/с\n\nПоддерживаются только публичные видеопубликации. Приватные аккаунты, материалы с авторизацией, изображения, фотографии и карусели не поддерживаются.\n\nКоманды:\n/start — Открыть приветствие\n/help — Показать эту справку\n/download <ссылка> — Начать загрузку\n/feedback <текст> — Отправить отзыв\n/support — Поддержать бота\n/settings — Изменить язык"
_TEXT["az"]["help"] = "🎬 Botdan necə istifadə etməli\n\n1. YouTube, TikTok, Instagram, Facebook, X və ya LinkedIn-dən ictimai video linki göndərin.\n2. Video keyfiyyətini və ya MP3 bitreytini seçin.\n3. Telegram limitinə uyğun fayllar üçün Telegram-a göndərilməni və ya müvəqqəti linki seçin. Böyük fayllar avtomatik olaraq müvəqqəti linklə təqdim edilir.\n\nMövcud seçimlər:\n• Video: 360p, 480p, 720p, 1080p və ya ən yaxşı keyfiyyət\n• Audio: 128, 192 və ya 320 kbit/s MP3\n\nYalnız ictimai video paylaşımları dəstəklənir. Şəxsi hesablar, giriş tələb edən məzmun, şəkillər və karusellər dəstəklənmir.\n\nƏmrlər:\n/start — Xoş gəldiniz ekranını göstər\n/help — Bu izahı göstər\n/download <link> — Yükləməyə başla\n/feedback <mətn> — Rəy göndər\n/support — Bota dəstək ol\n/settings — Dili dəyiş"

_TEXT["en"].update({
    "transcribe": "📝 Transcribe speech",
    "summarize": "📌 Summarize video",
    "transcribe_usage": "Usage: /transcribe <https-video-url>",
    "transcribe_url": "Please provide one valid HTTPS video URL to transcribe.",
    "transcription_unavailable": "Speech-to-text is not available right now. Please try again later.",
    "transcription_storage": "Speech-to-text requires cloud storage to be configured. Please try again later.",
    "transcription_queue_unavailable": "Speech-to-text is temporarily busy. Please try again later.",
    "transcription_saved_for_retry": "⚠️ The queue is temporarily unavailable. Your job was saved and will retry automatically; you do not need to send it again.",
    "transcription_retrying_soon": "⚠️ Attempt {attempt} paused because of a temporary service problem. Your job is safe and will retry in less than a minute—do not send it again.",
    "transcription_retrying": "⚠️ Attempt {attempt} paused because of a temporary service problem. Your job is safe and will retry in about {retry_minutes} min—do not send it again.",
    "transcription_queued": "🕒 Your transcription is queued. I’ll send it when processing is complete.",
    "transcription_queued_with_position": "🕒 Your transcription is queued at position {position}. Estimated wait: about {eta_minutes} min.",
    "transcription_starting": "📝 Starting transcription…",
    "transcription_processing": "🧠 Transcribing speech… This can take a few minutes for long videos.",
    "summarization_processing": "🧠 Generating the summary from the transcript…",
    "transcription_ready": "📝 Transcript ready · detected language: {detected_language}",
    "transcription_fallback": "The source could not be checked for download formats. You can still try speech-to-text:",
})
_TEXT["ru"].update({
    "transcribe": "📝 Расшифровать речь",
    "summarize": "📌 Кратко пересказать видео",
    "transcribe_usage": "Использование: /transcribe <https-ссылка-на-видео>",
    "transcribe_url": "Укажите корректную HTTPS-ссылку на видео для расшифровки.",
    "transcription_unavailable": "Преобразование речи в текст сейчас недоступно. Попробуйте позже.",
    "transcription_storage": "Для расшифровки нужно настроить облачное хранилище. Попробуйте позже.",
    "transcription_queue_unavailable": "Преобразование речи в текст временно занято. Попробуйте позже.",
    "transcription_saved_for_retry": "⚠️ Очередь временно недоступна. Задание сохранено и будет повторено автоматически — отправлять его снова не нужно.",
    "transcription_retrying_soon": "⚠️ Попытка {attempt} приостановлена из-за временной ошибки сервиса. Задание сохранено и повторится менее чем через минуту — не отправляйте его снова.",
    "transcription_retrying": "⚠️ Попытка {attempt} приостановлена из-за временной ошибки сервиса. Задание сохранено и повторится примерно через {retry_minutes} мин — не отправляйте его снова.",
    "transcription_queued": "🕒 Ваша расшифровка поставлена в очередь. Я отправлю её после обработки.",
    "transcription_queued_with_position": "🕒 Ваша расшифровка в очереди на позиции {position}. Ожидаемое время: около {eta_minutes} мин.",
    "transcription_starting": "📝 Запускаю расшифровку…",
    "transcription_processing": "🧠 Расшифровываю речь… Для длинных видео это может занять несколько минут.",
    "summarization_processing": "🧠 Готовлю краткое содержание по расшифровке…",
    "transcription_ready": "📝 Расшифровка готова · определённый язык: {detected_language}",
    "transcription_fallback": "Источник не удалось проверить для выбора формата. Можно попробовать расшифровку речи:",
})
_TEXT["az"].update({
    "transcribe": "📝 Nitqi mətnə çevir",
    "summarize": "📌 Videonu xülasə et",
    "transcribe_usage": "İstifadə: /transcribe <https-video-linki>",
    "transcribe_url": "Mətnə çevirmək üçün düzgün HTTPS video linki göndərin.",
    "transcription_unavailable": "Nitqin mətnə çevrilməsi hazırda əlçatan deyil. Sonra yenidən cəhd edin.",
    "transcription_storage": "Nitqi mətnə çevirmək üçün bulud yaddaşı konfiqurasiya edilməlidir. Sonra yenidən cəhd edin.",
    "transcription_queue_unavailable": "Nitqin mətnə çevrilməsi müvəqqəti olaraq məşğuldur. Sonra yenidən cəhd edin.",
    "transcription_saved_for_retry": "⚠️ Növbə müvəqqəti əlçatan deyil. Tapşırıq yadda saxlanıldı və avtomatik təkrar ediləcək — yenidən göndərməyiniz lazım deyil.",
    "transcription_retrying_soon": "⚠️ {attempt}-ci cəhd müvəqqəti xidmət problemi səbəbilə dayandırıldı. Tapşırığınız təhlükəsizdir və bir dəqiqədən az müddətdə təkrar ediləcək — yenidən göndərməyin.",
    "transcription_retrying": "⚠️ {attempt}-ci cəhd müvəqqəti xidmət problemi səbəbilə dayandırıldı. Tapşırığınız təhlükəsizdir və təxminən {retry_minutes} dəqiqəyə təkrar ediləcək — yenidən göndərməyin.",
    "transcription_queued": "🕒 Transkripsiyanız növbəyə əlavə edildi. Hazır olduqda sizə göndərəcəyəm.",
    "transcription_queued_with_position": "🕒 Transkripsiyanız növbədə {position}-ci yerdədir. Təxmini gözləmə: {eta_minutes} dəqiqə.",
    "transcription_starting": "📝 Transkripsiya başlayır…",
    "transcription_processing": "🧠 Nitq mətnə çevrilir… Uzun videolar üçün bu, bir neçə dəqiqə çəkə bilər.",
    "summarization_processing": "🧠 Xülasə transkripsiya əsasında hazırlanır…",
    "transcription_ready": "📝 Transkripsiya hazırdır · müəyyən edilən dil: {detected_language}",
    "transcription_fallback": "Format seçimi üçün mənbəni yoxlamaq mümkün olmadı. Nitqi mətnə çevirməyə cəhd edə bilərsiniz:",
})
_TEXT["en"]["transcription_help"] = "📝 Want text instead? Tap ‘Transcribe speech’ after sending a link, or use /transcribe <link>. The bot returns a timestamped .txt file."
_TEXT["ru"]["transcription_help"] = "📝 Нужен текст? Нажмите «Расшифровать речь» после отправки ссылки или используйте /transcribe <ссылка>. Бот вернёт .txt-файл с таймкодами."
_TEXT["az"]["transcription_help"] = "📝 Mətn lazımdır? Link göndərdikdən sonra «Nitqi mətnə çevir» düyməsinə basın və ya /transcribe <link> əmrindən istifadə edin. Bot vaxt göstəricili .txt faylı qaytaracaq."

_TEXT["en"].update({
    "credits_title": "💳 Your account", "credits_balance": "Credits: {available} available · {reserved} reserved",
    "credits_unlimited": "Credits: unlimited", "ai_trials": "AI trials: {trials} ({reserved} reserved)",
    "ai_unlimited": "AI transcription & summaries: unlimited", "ai_cost": "AI transcription or summary: {cost} credits", "premium_active": "Premium active until {date}",
    "complimentary_active": "Complimentary unlimited access", "free_account": "Free account",
    "referral_progress": "Invites: {qualified} rewarded · {pending} pending",
    "invite_button": "🎁 Invite friends", "upgrade_button": "⭐ Upgrade", "cancel_renewal_button": "Stop renewal",
    "need_credits": "You need {cost} credits for this AI request. Your link is still here—invite friends to earn more credits, then try again.",
    "need_ai_trials": "Your {trials} free AI trials are used. Your link is still here—upgrade for unlimited transcripts and summaries.",
    "account_unavailable": "Account service is temporarily unavailable. Nothing was charged; please try again shortly.",
    "invite_text": "🎁 Invite friends\n\nShare this link:\n{url}\n\nWhen a new user successfully uses the bot for the first time, you both receive {inviter_reward} credits. Up to {cap} rewarded invites every rolling 30 days.",
    "referral_attached": "Referral accepted. Use the bot successfully once to unlock {reward} bonus credits.",
    "premium_offer": "⭐ Premium · {price} Telegram Stars every 30 days\n\nUnlimited download credits and unlimited transcripts and summaries, subject to the same fair-use and capacity limits. Renewal can be stopped any time; access lasts until the paid period ends. Payment is handled by Telegram; Stars can be purchased through Telegram on iPhone or Android.",
    "premium_unavailable": "Premium checkout is not open yet. You can keep using the bot normally.",
    "premium_already_active": "Premium is already active on this account. Use /credits to view or stop renewal.",
    "buy_premium": "Continue to payment", "premium_paid": "✅ Premium is active. You now have unlimited credits and AI access.",
    "premium_payment_invalid": "This payment request expired or does not match your account. Open /premium and try again.",
    "renewal_cancelled": "Renewal is off. Premium remains active until {date}.", "renewal_cancel_failed": "I could not stop renewal right now. Contact /paysupport.",
    "terms": "Terms\n\nUse this bot only for media you own or are permitted to download. You are responsible for complying with copyright and platform rules. Premium provides unlimited credits, not unrestricted infrastructure; fair-use rate and capacity limits still apply. Subscriptions renew every 30 days until cancelled. Access continues through the paid period after cancellation.",
    "paysupport": "Payment support\n\nFor a payment, renewal, or refund request, send /feedback with the approximate payment time and a short description. Refund requests are reviewed case by case. Never send passwords, payment card details, or login cookies.",
    "referral_rewarded": "🎉 Referral unlocked: {credits} permanent credits were added.",
    "account_help": "Account commands:\n/credits — View your credit balance\n/invite — Invite friends and earn credits",
    "account_private_only": "Open a private chat with the bot to view your account or make a payment.",
    "premium_invoice_title": "Downloader Premium", "premium_invoice_description": "Unlimited credits and AI access for 30 days (fair-use limits apply)", "premium_invoice_price": "Premium · 30 days",
})
_TEXT["ru"].update({
    "credits_title": "💳 Ваш аккаунт", "credits_balance": "Кредиты: {available} доступно · {reserved} зарезервировано", "credits_unlimited": "Кредиты: безлимитно",
    "ai_trials": "Пробные AI-функции: {trials} ({reserved} зарезервировано)", "ai_cost": "Транскрипция или сводка: {cost} кредитов", "ai_unlimited": "Расшифровки и сводки: безлимитно",
    "premium_active": "Premium активен до {date}", "complimentary_active": "Бесплатный безлимитный доступ", "free_account": "Бесплатный аккаунт",
    "referral_progress": "Приглашения: {qualified} награждено · {pending} ожидает", "invite_button": "🎁 Пригласить", "upgrade_button": "⭐ Premium", "cancel_renewal_button": "Остановить продление",
    "need_credits": "Для этого AI-запроса нужно {cost} кредитов. Ссылка сохранена — пригласите друзей, чтобы получить кредиты, и попробуйте снова.",
    "need_ai_trials": "{trials} бесплатные AI-попытки использованы. Ссылка сохранена — Premium даёт безлимитные расшифровки и сводки.",
    "account_unavailable": "Сервис аккаунтов временно недоступен. Кредит не списан; повторите позже.",
    "invite_text": "🎁 Пригласите друзей\n\nПоделитесь ссылкой:\n{url}\n\nКогда новый пользователь выполнит {required} загрузки, вы получите {inviter_reward} кредитов, а он — {invitee_reward}. До {cap} наград за любые 30 дней.",
    "referral_attached": "Приглашение принято. Выполните {required} загрузки, чтобы получить {reward} бонусных кредитов.",
    "premium_offer": "⭐ Premium · {price} Telegram Stars каждые 30 дней\n\nБезлимитные кредиты, расшифровки и сводки при обычных лимитах честного использования и мощности. Продление можно отключить в любой момент. Оплату обрабатывает Telegram; Stars можно купить в Telegram на iPhone или Android.",
    "premium_unavailable": "Оплата Premium пока не открыта. Вы можете продолжать пользоваться ботом как обычно.",
    "premium_already_active": "Premium уже активен. Откройте /credits, чтобы посмотреть статус или отключить продление.",
    "buy_premium": "Перейти к оплате", "premium_paid": "✅ Premium активен. Кредиты и AI-функции теперь безлимитны.", "premium_payment_invalid": "Счёт истёк или не принадлежит аккаунту. Откройте /premium снова.",
    "renewal_cancelled": "Продление отключено. Premium активен до {date}.", "renewal_cancel_failed": "Не удалось отключить продление. Обратитесь через /paysupport.",
    "terms": "Условия\n\nИспользуйте бот только для материалов, которые вам принадлежат или которые разрешено скачивать. Вы отвечаете за соблюдение авторских прав и правил платформ. Premium означает безлимитные кредиты, но обычные лимиты честного использования и мощности сохраняются. Подписка продлевается каждые 30 дней до отмены.",
    "paysupport": "Поддержка платежей\n\nДля решения проблемы с оплатой, продлением или запроса возврата отправьте /feedback с примерным временем платежа и описанием. Запросы возврата рассматриваются индивидуально. Не отправляйте пароли, данные карты или cookies.", "referral_rewarded": "🎉 Награда за приглашение: добавлено {credits} постоянных кредитов.",
    "account_help": "Команды аккаунта:\n/credits — Посмотреть баланс\n/invite — Пригласить друзей и получить кредиты",
    "account_private_only": "Откройте личный чат с ботом, чтобы посмотреть аккаунт или оплатить подписку.",
    "premium_invoice_title": "Downloader Premium", "premium_invoice_description": "Безлимитные кредиты и AI на 30 дней с лимитами честного использования", "premium_invoice_price": "Premium · 30 дней",
})
_TEXT["az"].update({
    "credits_title": "💳 Hesabınız", "credits_balance": "Kreditlər: {available} mövcuddur · {reserved} rezervdə", "credits_unlimited": "Kreditlər: limitsiz",
    "ai_trials": "AI sınaqları: {trials} ({reserved} rezervdə)", "ai_cost": "Transkripsiya və ya xülasə: {cost} kredit", "ai_unlimited": "Transkripsiya və xülasələr: limitsiz",
    "premium_active": "Premium {date} tarixinədək aktivdir", "complimentary_active": "Hədiyyə limitsiz giriş", "free_account": "Pulsuz hesab",
    "referral_progress": "Dəvətlər: {qualified} mükafatlandırılıb · {pending} gözləyir", "invite_button": "🎁 Dost dəvət et", "upgrade_button": "⭐ Premium", "cancel_renewal_button": "Yenilənməni dayandır",
    "need_credits": "Bu AI sorğusu üçün {cost} kredit lazımdır. Link saxlanılıb — kredit qazanmaq üçün dostlarınızı dəvət edin və yenidən cəhd edin.",
    "need_ai_trials": "{trials} pulsuz AI sınağı bitib. Link saxlanılıb — Premium limitsiz transkripsiya və xülasə verir.",
    "account_unavailable": "Hesab xidməti müvəqqəti əlçatan deyil. Kredit tutulmadı; bir az sonra yenidən cəhd edin.",
    "invite_text": "🎁 Dostlarınızı dəvət edin\n\nBu linki paylaşın:\n{url}\n\nYeni istifadəçi {required} yükləməni tamamlayanda siz {inviter_reward}, o isə {invitee_reward} kredit qazanır. Hər 30 gündə {cap} mükafatadək.",
    "referral_attached": "Dəvət qəbul edildi. {reward} bonus kredit üçün {required} yükləməni tamamlayın.",
    "premium_offer": "⭐ Premium · hər 30 gün üçün {price} Telegram Stars\n\nAdi ədalətli istifadə və tutum limitləri daxilində limitsiz kredit, transkripsiya və xülasə. Yenilənməni istənilən vaxt dayandırmaq olar. Ödənişi Telegram emal edir; Stars iPhone və ya Android-də Telegram daxilindən alına bilər.",
    "premium_unavailable": "Premium ödənişi hələ açıq deyil. Botdan adi qaydada istifadə edə bilərsiniz.",
    "premium_already_active": "Premium artıq aktivdir. Statusa baxmaq və ya yenilənməni dayandırmaq üçün /credits açın.",
    "buy_premium": "Ödənişə keç", "premium_paid": "✅ Premium aktivdir. Kreditlər və AI imkanları limitsizdir.", "premium_payment_invalid": "Ödəniş sorğusu bitib və ya hesabınıza uyğun deyil. /premium əmrini yenidən açın.",
    "renewal_cancelled": "Yenilənmə söndürüldü. Premium {date} tarixinədək aktivdir.", "renewal_cancel_failed": "Yenilənməni dayandırmaq mümkün olmadı. /paysupport ilə əlaqə saxlayın.",
    "terms": "Şərtlər\n\nBotdan yalnız sizə məxsus və ya yükləməyə icazəniz olan media üçün istifadə edin. Müəllif hüquqları və platforma qaydalarına əməl etmək sizin məsuliyyətinizdir. Premium limitsiz kredit deməkdir; ədalətli istifadə və tutum limitləri qalır. Abunə ləğv edilənədək hər 30 gündə yenilənir.",
    "paysupport": "Ödəniş dəstəyi\n\nÖdəniş, yenilənmə və ya geri qaytarma sorğusu üçün təxmini ödəniş vaxtı və qısa izahla /feedback göndərin. Geri qaytarma sorğuları fərdi qaydada nəzərdən keçirilir. Şifrə, kart məlumatı və cookies göndərməyin.", "referral_rewarded": "🎉 Dəvət mükafatı: {credits} daimi kredit əlavə edildi.",
    "account_help": "Hesab əmrləri:\n/credits — Kredit balansına bax\n/invite — Dostları dəvət et və kredit qazan",
    "account_private_only": "Hesabınıza baxmaq və ya ödəniş etmək üçün botla şəxsi söhbəti açın.",
    "premium_invoice_title": "Downloader Premium", "premium_invoice_description": "Ədalətli istifadə limitləri ilə 30 günlük limitsiz kredit və AI girişi", "premium_invoice_price": "Premium · 30 gün",
})


def normalize_language(language: str | None) -> str:
    return language if language in SUPPORTED_LANGUAGES else "en"


def tr(language: str | None, key: str, **values: Any) -> str:
    lang = normalize_language(language)
    text = _TEXT.get(lang, _TEXT["en"]).get(key, _TEXT["en"].get(key, key))
    return text.format(**values) if values else text


def language_keyboard() -> Any:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(LANGUAGE_NAMES["en"], callback_data="lang|en"),
        InlineKeyboardButton(LANGUAGE_NAMES["ru"], callback_data="lang|ru"),
        InlineKeyboardButton(LANGUAGE_NAMES["az"], callback_data="lang|az"),
    ]])
