# Хостирање на Microsoft Azure и експорт на базата

## 1. База на податоци – Azure Database for MySQL

- Креирај **Azure Database for MySQL** (Flexible Server препорачано).
- Во **backend/.env** постави:
  - `DB_HOST=tvoja-server.mysql.database.azure.com`
  - `DB_USER=tvoja_korisnicko@tvoja-server` (формат за Azure)
  - `DB_PASSWORD=...`
  - `DB_NAME=Klinicka_Bolnica_Stip`
  - `DB_SSL=1` (за SSL конекција)
- Доколку Azure бара SSL сертификат, симни [DigiCertGlobalRootCA.crt](https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem) и во `.env` додај: `DB_SSL_CA=/path/to/DigiCertGlobalRootCA.crt`.

## 2. Миграција на базата на Azure (MySQL Workbench)

Апликацијата користи **mysql.connector**; нема вградено LIMIT за лекари – сите редови се читаат од базата.

### Зошто во MySQL Workbench се појавуваат само 15 лекари?

MySQL Workbench по default при приказ на табела и при **експорт** ограничува редови (на пр. „Limit Rows“). Тоа е само поставка на алатката, не на базата.

### Како да ги експортираш **сите** податоци (на пр. сите 90+ лекари):

1. **Server → Data Export**
   - Избери база и табели (на пр. `Doctors` и останати).
   - Експортот ќе ги земе **сите** редови (не само 15).

2. **Или зголеми лимит на редови при приказ**
   - При отворање на табела: под табелата има „Limit Rows“. Постави голем број (на пр. 1000) или „No Limit“ ако понуди.

3. **Или со mysqldump од терминал** (сите редови):
   ```bash
   mysqldump -h localhost -u root -p Klinicka_Bolnica_Stip > dump.sql
   ```
   За Azure:
   ```bash
   mysqldump -h tvoja-server.mysql.database.azure.com -u tvoja_korisnicko@tvoja-server -p --ssl-mode=REQUIRED Klinicka_Bolnica_Stip > dump.sql
   ```

По експорт, увоз во Azure: **Server → Data Import** и избери го `dump.sql`, или:
```bash
mysql -h tvoja-server.mysql.database.azure.com -u ... -p --ssl-mode=REQUIRED Klinicka_Bolnica_Stip < dump.sql
```

## 3. Дебаг на конекцијата и број на лекари

Во **backend/.env** додај:
```env
DEBUG_DB=1
```
При секоја конекција ќе се испечати дали конекцијата е успешна и колку редови има во табелата `Doctors`. Користи го за да потврдиш дека апликацијата ги чита сите лекари од базата.

---

## 4. Слики на новости преку Azure Blob Storage (контејнер)

За да ставиш слика на новост од Blob контејнерот, следи ја оваа процедура:

### Чекор 1: Качи слика во Blob контејнерот

1. Отвори **Azure Portal** → **Storage accounts** → избери го твојот storage (на пр. `kbstipstorage`).
2. Во левото мени избери **Containers** → отвори го контејнерот (на пр. `kbstiptcontaine`).
3. Кликни **Upload**.
4. Избери слика од компјутерот (JPG, PNG, WEBP).
5. Кликни **Upload**.
6. По завршување, кликни на името на фајлот.
7. Копирај го **URL**-от од десната страна (на пр. `https://kbstipstorage.blob.core.windows.net/kbstiptcontaine/ime-na-slika.jpg`).

### Чекор 2: Додај URL во формата за новост

1. Најави се како **директор** на апликацијата.
2. Отвори **Новости** → **Додади новост** или **Уреди** постоечка.
3. Во полето **„URL на слика (Azure Blob или друг URL)“** вметни го копираниот URL.
4. За **дополнителни слики** (галерија): во полето **„URL-и на дополнителни слики“** вметни по еден URL на ред.
5. Кликни **Зачувај**.

### Формат на URL

```
https://kbstipstorage.blob.core.windows.net/kbstiptcontaine/ime-na-slika.jpg
```

- Замени `kbstipstorage` со името на твојот storage account.
- Замени `kbstiptcontaine` со името на твојот контејнер.
- Името на фајлот е она што го качиш (на пр. `novost-1.jpg`).

### Важно

- **Blob контејнерот** мора да има **Public access** (Blob или Container) за да сликите се вчитуваат на јавната страница.
- Ако имаш проблеми при приказ: проверка дали URL-от е правилен во DevTools → Network.
