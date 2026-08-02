// تم التحديث بالرابط النهائي الصحيح للباك إند
const BACKEND_URL = "https://bob-2-production.up.railway.app/api/v1/erp/chat-spreadsheet";

// جلب العناصر من واجهة المستخدم
const chatBox = document.getElementById("chatBox");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const fileInput = document.getElementById("fileInput");

// إضافة المستمعين للأحداث (بدلاً من كتابتها في HTML)
sendBtn.addEventListener("click", sendMessage);

messageInput.addEventListener("keypress", function(event) {
    if (event.key === "Enter") {
        sendMessage();
    }
});

// الدالة الرئيسية لإرسال البيانات
function sendMessage() {
    const text = messageInput.value.trim();
    const file = fileInput.files[0];

    // إذا لم يكتب المستخدم شيئاً ولم يرفق ملفاً، توقف
    if (text === "" && !file) return; 

    // 1. عرض رسالة المستخدم في الشاشة
    if (text) {
        appendMessage("user", text);
    }
    if (file) {
        appendMessage("user", `📎 تم إرفاق ملف: ${file.name}`);
    }

    // 2. تفريغ الحقول بعد الإرسال
    messageInput.value = "";
    fileInput.value = "";

    // 3. تجهيز البيانات لإرسالها للباك إند
    const formData = new FormData();
    if (text) formData.append("message", text);
    if (file) formData.append("file", file);

    // 4. إرسال الطلب إلى Railway (الباك إند)
    fetch(BACKEND_URL, {
        method: "POST",
        body: formData // نستخدم FormData لدعم رفع الملفات بشكل صحيح
    })
    .then(response => {
        if (!response.ok) {
            throw new Error("حدث خطأ في الاتصال بخادم BOB-2");
        }
        return response.json();
    })
    .then(data => {
        // افترضنا هنا أن الباك إند يرد بمتغير اسمه 'reply' - قم بتعديله حسب برمجتك للباك إند
        const botReply = data.reply || "تمت معالجة البيانات بنجاح.";
        appendMessage("bot", botReply);
    })
    .catch(error => {
        console.error("Error:", error);
        appendMessage("bot", "❌ عذراً، تعذر الاتصال بالخادم. يرجى التحقق من الرابط أو حالة الباك إند.");
    });
}

// دالة مساعدة لطباعة الرسائل في الشاشة
function appendMessage(sender, text) {
    const messageElement = document.createElement("div");
    messageElement.classList.add("message");
    
    if (sender === "user") {
        messageElement.classList.add("user-message");
    } else {
        messageElement.classList.add("bot-message");
    }

    messageElement.textContent = text;
    chatBox.appendChild(messageElement);
    
    // التمرير التلقائي لأسفل الشاشة لرؤية الرسالة الجديدة
    chatBox.scrollTop = chatBox.scrollHeight;
}
