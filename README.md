Lista na site pacient kaj daden lekar, na sekoj lekar mu se dava koj pacienti imat napraveno pregled kaj nego na primer vo prethodnite 3 meseca

Pregled na cela medicinska istorija na daden pacient, dijagnozi terapija i se to 

PATCH /pacienti/{pacient_id}: Ажурирање на основни податоци како телефон или адреса.

PATCH /termini/{termin_id}/status: Промена на статусот на терминот (на пр. од „закажан“ во „завршен“, „откажан“ или „не се појавил“).

POST /termini/{termin_id}/izveshtaj: Лекарот да може да внесе детален извештај, дијагноза и терапија директно за тој термин

GET /termini/deneshni: Брз преглед на сите термини за тековниот ден за најавениот лекар.

GET /admin/statistika/pregledi: Број на извршени прегледи по оддели во послениот месец.

GET /admin/statistika/aparati: Колку често се користат апаратите (MRI, CT) за да се планира одржување

GET /admin/lekari/aktivnost: Преглед на бројот на дежурства и прегледи по лекар.

POST /recepti: Креирање дигитален рецепт поврзан со дијагнозата од терминот.

POST /notifikacii/isprati-potvrda: Ендпоинт кој би испраќал автоматски email до пациентот за потврда на неговиот термин.

GET /izvestuvanja/admin: Глобални известувања за сите вработени (на пр. промена во работно време или нови огласи за кариера).