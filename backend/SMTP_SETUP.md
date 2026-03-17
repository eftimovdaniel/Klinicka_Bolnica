# Поставување на SMTP за е-пошта (потврда за термин)

## Грешка: "Username and Password not accepted" (535)

Оваа грешка се појавува кога Google не ги прифаќа SMTP credentials во `.env`.

### Решение за Gmail

1. **Овозможи 2FA** на Google сметката (ако веќе не е)
2. **Креирај App Password**:
   - Отвори https://myaccount.google.com/apppasswords
   - Избери „Mail“ и „Other“ (друго уред)
   - Копирај го 16-цифрениот код (напр. `xhrn qcso xtza jhsx`)
3. **Ажурирај `.env`**:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=tvoj.email@gmail.com
   SMTP_PASSWORD=xxxx xxxx xxxx xxxx
   EMAIL_FROM=tvoj.email@gmail.com
   ```

**Важно:** Користи App Password, не обична лозинка. Google блокира најава со обична лозинка од апликации.

### Терминот се закажува успешно

Дури и кога е-поштата не се испраќа (SMTP грешка), **терминот се зачувува во базата**. Backend враќа 200 OK и потврдата се прикажува на корисникот. Грешката со е-пошта се печати само во конзолата на серверот.
