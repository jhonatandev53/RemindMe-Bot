import os
import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.error import Forbidden
from database import Database
from bson import ObjectId

load_dotenv()

class RemindMeBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.db = Database()
        self.app = ApplicationBuilder().token(self.token).build()
        self.register_handlers()
        self.register_jobs()

    def register_handlers(self):
        # Registramos comandos y el escuchador de botones interactivos
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("tasks", self.tasks_command))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))

    def register_jobs(self):
        # Configuramos el JobQueue para que ejecute la revisión cada 60 segundos
        job_queue = self.app.job_queue
        job_queue.run_repeating(self.check_tasks_job, interval=60, first=10)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        chat_id_str = str(telegram_user.id)
        
        users_col = self.db.get_collection("users")
        user_doc = users_col.find_one({"telegramId": chat_id_str})

        if user_doc:
            # Si el usuario se vuelve a conectar, nos aseguramos de reactivar su estado en la BD
            users_col.update_one({"_id": user_doc["_id"]}, {"$set": {"telegramActive": True}})

            await update.message.reply_text(
                f"¡Hola, {user_doc.get('name', telegram_user.first_name)}! 👋🏻\n\n"
                f"✅ ¡Tu cuenta ya está vinculada correctamente a **RemindMe**!\n"
                f"Tu Chat ID (`{chat_id_str}`) está activo y listo para recibir tus alertas. 🚀",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"¡Hola, {telegram_user.first_name}! 👋🏻\n\n"
                f"Tu ID de Telegram es: `{chat_id_str}`\n\n"
                f"⚠️ No encontré este ID en la base de datos. Ve a tu perfil en la web de RemindMe, pégalo en tu campo de Telegram y guarda los cambios. ",
                parse_mode="Markdown"
            )

    async def tasks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Consulta bajo demanda todas las tareas pendientes del usuario"""
        telegram_user = update.effective_user
        chat_id_str = str(telegram_user.id)

        users_col = self.db.get_collection("users")
        user_doc = users_col.find_one({"telegramId": chat_id_str})

        if not user_doc:
            await update.message.reply_text(
                "⚠️ Tu cuenta de Telegram no está vinculada. Usa el comando /start para ver las instrucciones.",
                parse_mode="Markdown"
            )
            return

        user_id = user_doc["_id"]
        tasks_col = self.db.get_collection("tasks")

        pending_tasks = list(tasks_col.find({"user": user_id, "completed": False}).sort("date", 1))

        if not pending_tasks:
            await update.message.reply_text(
                "🎉 ¡Excelente noticia! No tienes tareas pendientes en este momento.",
                parse_mode="Markdown"
            )
            return

        text = "🟡 **Tus tareas pendientes actuales:**\n\n"
        keyboard = []

        for task in pending_tasks:
            title = task.get("title", "Sin título")
            date = task.get("date", "")
            time = task.get("time", "")
            
            text += f"📌 **{title}**\n   📅 {date} a las ⏰ {time}\n\n"
            
            btn_title = title if len(title) <= 22 else title[:19] + "..."
            
            keyboard.append([
                InlineKeyboardButton(f"✅ Completar: {btn_title}", callback_data=f"complete_{task['_id']}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    async def check_tasks_job(self, context: ContextTypes.DEFAULT_TYPE):
        """Revisa cada minuto si hay tareas pendientes por notificar con manejo avanzado de errores"""
        tasks_col = self.db.get_collection("tasks")
        users_col = self.db.get_collection("users")

        now = datetime.datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")

        print(f"Buscando tareas para fecha: {current_date} y hora: {current_time}...")

        query = {
            "date": current_date,
            "time": current_time,
            "completed": False,
            "notified": {"$ne": True}
        }

        pending_tasks = list(tasks_col.find(query))

        for task in pending_tasks:
            user_id = task.get("user")
            title = task.get("title", "Sin título")
            description = task.get("description", "Sin descripción")

            user_doc = users_col.find_one({"_id": ObjectId(user_id)})

            # Verificamos que el usuario exista y tenga activo su canal de Telegram
            if user_doc and user_doc.get("telegramId") and user_doc.get("telegramActive", True):
                chat_id = user_doc.get("telegramId")
                
                message = (
                    "🟡 **¡RECORDATORIO DE REMINDME!** 🟡\n\n"
                    f"📌 **Tarea:** {title}\n"
                    f"📝 **Descripción:** {description}\n"
                    f"⏰ **Hora programada:** {current_time}\n\n"
                    "¡Es hora de darle con toda! 🔥"
                )

                keyboard = [
                    [
                        InlineKeyboardButton("✅ Completar", callback_data=f"complete_{task['_id']}"),
                        InlineKeyboardButton("⏰ Posponer 10 min", callback_data=f"snooze_{task['_id']}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                try:
                    await context.bot.send_message(
                        chat_id=int(chat_id), 
                        text=message, 
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
                    
                    tasks_col.update_one({"_id": task["_id"]}, {"$set": {"notified": True}})
                    print(f"✅ Recordatorio enviado exitosamente al chat_id: {chat_id}")
                    
                except Forbidden:
                    # Capturamos cuando el usuario bloquea el bot o elimina el chat
                    print(f"⚠️️ [Aviso] El usuario con chat_id {chat_id} bloqueó el bot o cerró el chat. Actualizando estado en BD...")
                    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": {"telegramActive": False}})
                    
                except Exception as e:
                    print(f"❌ Error inesperado al enviar mensaje a Telegram: {e}")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Atrapa el clic de los botones interactivos (Completar o Posponer) y actualiza la base de datos"""
        query = update.callback_query
        await query.answer()

        data = query.data
        tasks_col = self.db.get_collection("tasks")

        if data.startswith("complete_"):
            task_id = data.split("_")[1]

            result = tasks_col.update_one(
                {"_id": ObjectId(task_id)},
                {"$set": {"completed": True, "notified": True}}
            )

            if result.modified_count > 0 or result.matched_count > 0:
                original_text = query.message.text
                updated_text = original_text + "\n\n✅ *¡TAREA COMPLETADA DESDE TELEGRAM!* "
                await query.edit_message_text(text=updated_text, parse_mode="Markdown", reply_markup=None)
            else:
                await query.answer("⚠️ No se pudo actualizar la tarea o ya estaba completada.", show_alert=True)

        elif data.startswith("snooze_"):
            task_id = data.split("_")[1]

            new_time_dt = datetime.datetime.now() + datetime.timedelta(minutes=10)
            new_date = new_time_dt.strftime("%Y-%m-%d")
            new_time = new_time_dt.strftime("%H:%M")

            result = tasks_col.update_one(
                {"_id": ObjectId(task_id)},
                {
                    "$set": {
                        "date": new_date,
                        "time": new_time,
                        "notified": False
                    }
                }
            )

            if result.modified_count > 0 or result.matched_count > 0:
                original_text = query.message.text
                updated_text = original_text + f"\n\n *¡Tarea pospuesta 10 minutos!* Te avisaremos a las `{new_time}`. 🔄"
                await query.edit_message_text(text=updated_text, parse_mode="Markdown", reply_markup=None)
            else:
                await query.answer("⚠️ No se pudo posponer la tarea.", show_alert=True)

# Registro del menú del bot para BotFather
    def run(self):
        print("🤖 Bot de RemindMe blindado con manejo de bloqueos y motor activo...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = RemindMeBot()
    bot.run()