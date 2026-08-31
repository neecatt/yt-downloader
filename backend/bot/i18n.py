from __future__ import annotations

from typing import Any

SUPPORTED_LANGUAGES = ("en", "ru", "az")
LANGUAGE_NAMES = {"en": "🇬🇧 English", "ru": "🇷🇺 Русский", "az": "🇦🇿 Azərbaycan dili"}

_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "welcome": "🎬 Welcome to your fast media downloader!\n\nSend me a public video link from:\n\n• YouTube\n• TikTok\n• Instagram\n• Facebook\n• X\n• LinkedIn\n\nAfter I analyze the link, you can choose:\n\n• 360p, 480p, 720p, or 1080p video\n• Best available quality\n• MP3 audio at 128, 192, or 320 kbps\n\nFor smaller files, you can choose whether to receive the media directly in Telegram or get a temporary download link. Larger files are automatically provided through a temporary download link.\n\nThe bot supports public video posts only. Private accounts, login-protected content, image posts, photo posts, and carousels are not supported.\n\nCommands:\n\n/start — Show the welcome message\n/download — Download a video using a link\n/feedback — Send feedback or suggest an improvement\n/support — Support the continued development of the bot\n\nEnjoy fast, simple, and convenient downloads. 🚀",
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
        "fast_360": "360p · fast", "quality_480": "480p", "quality_720": "720p", "quality_1080": "1080p",
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
        "welcome": "🎬 Добро пожаловать в быстрый загрузчик медиа!\n\nОтправьте публичную ссылку на видео из:\n\n• YouTube\n• TikTok\n• Instagram\n• Facebook\n• X\n• LinkedIn\n\nПосле анализа ссылки вы сможете выбрать:\n\n• Видео 360p, 480p, 720p или 1080p\n• Лучшее доступное качество\n• MP3 с битрейтом 128, 192 или 320 кбит/с\n\nДля небольших файлов можно выбрать отправку прямо в Telegram или временную ссылку для скачивания. Большие файлы автоматически выдаются по временной ссылке.\n\nПоддерживаются только публичные видеопубликации. Приватные аккаунты, материалы с авторизацией, изображения, фотографии и карусели не поддерживаются.\n\nКоманды:\n\n/start — Показать приветствие\n/download — Скачать видео по ссылке\n/feedback — Отправить отзыв или предложение\n/support — Поддержать развитие бота\n\nБыстрых и удобных загрузок! 🚀",
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
        "choose_format": "🎬 {title}{duration}\n\nВыберите формат:", "fast_360": "360p · быстро", "quality_480": "480p", "quality_720": "720p", "quality_1080": "1080p", "best": "Лучшее качество", "mp3_128": "MP3 · 128 кбит/с", "mp3_192": "MP3 · 192 кбит/с", "mp3_320": "MP3 · 320 кбит/с",
        "ready_choice": "✅ Готово: {title}\nРазмер: {size:.1f} МБ\n\nКак отправить файл?", "link_unconfigured": "Ссылки для скачивания не настроены. Выберите отправку в Telegram.", "delivery_expired": "Выбор доставки истёк. Отправьте ссылку ещё раз.", "upload_telegram": "⬆️ Отправляю в Telegram…\nЗагрузка: 100%", "prepare_link": "☁️ Подготавливаю ссылку…", "telegram_failed_other": "Telegram не смог принять файл. Попробуйте другой способ доставки.", "telegram_failed_quality": "Telegram не смог принять файл. Попробуйте более низкое качество.", "downloading": "⬇️ Загружаю {fmt}…", "upload_cloud": "☁️ Загружаю в облачное хранилище…\nЗагрузка: 100%", "already_running": "В этом чате уже выполняется загрузка. Подождите.", "download_limit": "Вы достигли лимита загрузок. Попробуйте позже.", "invalid_button": "Эта кнопка больше недействительна. Отправьте ссылку ещё раз.", "link_expired": "Срок действия ссылки истёк. Отправьте её ещё раз.", "ready_link_choice": "Вы выбрали временную ссылку для скачивания.", "ready_link_large": "Файл превышает лимит Telegram, поэтому я выдаю временную ссылку для скачивания.",
    },
    "az": {
        "welcome": "🎬 Sürətli media yükləyicisinə xoş gəlmisiniz!\n\nAşağıdakı platformalardan ictimai video linki göndərin:\n\n• YouTube\n• TikTok\n• Instagram\n• Facebook\n• X\n• LinkedIn\n\nLink analiz edildikdən sonra bunları seçə bilərsiniz:\n\n• 360p, 480p, 720p və ya 1080p video\n• Mövcud ən yaxşı keyfiyyət\n• 128, 192 və ya 320 kbit/s MP3\n\nKiçik fayllar üçün Telegram-a birbaşa göndərilməni və ya müvəqqəti yükləmə linkini seçə bilərsiniz. Böyük fayllar avtomatik olaraq müvəqqəti linklə təqdim edilir.\n\nYalnız ictimai video paylaşımları dəstəklənir. Şəxsi hesablar, giriş tələb edən məzmun, şəkil paylaşımları və karusellər dəstəklənmir.\n\nƏmrlər:\n\n/start — Xoş gəldiniz mesajını göstər\n/download — Linkdən video yüklə\n/feedback — Rəy və ya təklif göndər\n/support — Botun inkişafına dəstək ol\n\nSürətli və rahat yükləmələr! 🚀",
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
    "transcribe_usage": "Usage: /transcribe <https-video-url>",
    "transcribe_url": "Please provide one valid HTTPS video URL to transcribe.",
    "transcription_unavailable": "Speech-to-text is not available right now. Please try again later.",
    "transcription_storage": "Speech-to-text requires cloud storage to be configured. Please try again later.",
    "transcription_queue_unavailable": "Speech-to-text is temporarily busy. Please try again later.",
    "transcription_queued": "🕒 Your transcription is queued. I’ll send it when processing is complete.",
    "transcription_queued_with_position": "🕒 Your transcription is queued at position {position}. Estimated wait: about {eta_minutes} min.",
    "transcription_starting": "📝 Starting transcription…",
    "transcription_processing": "🧠 Transcribing speech… This can take a few minutes for long videos.",
    "transcription_ready": "📝 Transcript ready · detected language: {detected_language}",
    "transcription_fallback": "The source could not be checked for download formats. You can still try speech-to-text:",
})
_TEXT["ru"].update({
    "transcribe": "📝 Расшифровать речь",
    "transcribe_usage": "Использование: /transcribe <https-ссылка-на-видео>",
    "transcribe_url": "Укажите корректную HTTPS-ссылку на видео для расшифровки.",
    "transcription_unavailable": "Преобразование речи в текст сейчас недоступно. Попробуйте позже.",
    "transcription_storage": "Для расшифровки нужно настроить облачное хранилище. Попробуйте позже.",
    "transcription_queue_unavailable": "Преобразование речи в текст временно занято. Попробуйте позже.",
    "transcription_queued": "🕒 Ваша расшифровка поставлена в очередь. Я отправлю её после обработки.",
    "transcription_queued_with_position": "🕒 Ваша расшифровка в очереди на позиции {position}. Ожидаемое время: около {eta_minutes} мин.",
    "transcription_starting": "📝 Запускаю расшифровку…",
    "transcription_processing": "🧠 Расшифровываю речь… Для длинных видео это может занять несколько минут.",
    "transcription_ready": "📝 Расшифровка готова · определённый язык: {detected_language}",
    "transcription_fallback": "Источник не удалось проверить для выбора формата. Можно попробовать расшифровку речи:",
})
_TEXT["az"].update({
    "transcribe": "📝 Nitqi mətnə çevir",
    "transcribe_usage": "İstifadə: /transcribe <https-video-linki>",
    "transcribe_url": "Mətnə çevirmək üçün düzgün HTTPS video linki göndərin.",
    "transcription_unavailable": "Nitqin mətnə çevrilməsi hazırda əlçatan deyil. Sonra yenidən cəhd edin.",
    "transcription_storage": "Nitqi mətnə çevirmək üçün bulud yaddaşı konfiqurasiya edilməlidir. Sonra yenidən cəhd edin.",
    "transcription_queue_unavailable": "Nitqin mətnə çevrilməsi müvəqqəti olaraq məşğuldur. Sonra yenidən cəhd edin.",
    "transcription_queued": "🕒 Transkripsiyanız növbəyə əlavə edildi. Hazır olduqda sizə göndərəcəyəm.",
    "transcription_queued_with_position": "🕒 Transkripsiyanız növbədə {position}-ci yerdədir. Təxmini gözləmə: {eta_minutes} dəqiqə.",
    "transcription_starting": "📝 Transkripsiya başlayır…",
    "transcription_processing": "🧠 Nitq mətnə çevrilir… Uzun videolar üçün bu, bir neçə dəqiqə çəkə bilər.",
    "transcription_ready": "📝 Transkripsiya hazırdır · müəyyən edilən dil: {detected_language}",
    "transcription_fallback": "Format seçimi üçün mənbəni yoxlamaq mümkün olmadı. Nitqi mətnə çevirməyə cəhd edə bilərsiniz:",
})
_TEXT["en"]["transcription_help"] = "📝 Want text instead? Tap ‘Transcribe speech’ after sending a link, or use /transcribe <link>. The bot returns a timestamped .txt file."
_TEXT["ru"]["transcription_help"] = "📝 Нужен текст? Нажмите «Расшифровать речь» после отправки ссылки или используйте /transcribe <ссылка>. Бот вернёт .txt-файл с таймкодами."
_TEXT["az"]["transcription_help"] = "📝 Mətn lazımdır? Link göndərdikdən sonra «Nitqi mətnə çevir» düyməsinə basın və ya /transcribe <link> əmrindən istifadə edin. Bot vaxt göstəricili .txt faylı qaytaracaq."


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
