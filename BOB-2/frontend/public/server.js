const express = require('express');
const path = require('path');
const app = express();

// استخدام المنفذ الذي يحدده Railway تلقائياً
const PORT = process.env.PORT || 3000;

// إعداد سياسة أمان المحتوى (CSP) لتجاوز الحظر
app.use((req, res, next) => {
    res.setHeader(
        "Content-Security-Policy",
        // السماح بالملفات المحلية، والسماح بالاتصال برابط الباك إند
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' https://bob-2-production.up.railway.app;"
    );
    next();
});

// توجيه الخادم لتقديم الملفات الموجودة في نفس المجلد (index.html, style.css, script.js)
app.use(express.static(__dirname));

// تشغيل الخادم
app.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`);
});
