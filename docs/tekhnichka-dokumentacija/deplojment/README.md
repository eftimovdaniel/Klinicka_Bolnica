# Деплојмент

Во продукција, системот работи како три независни Docker контејнери — база на податоци, backend и frontend — кои заедно се кревааат и комуницираат преку внатрешна Docker мрежа, без потреба од рачно инсталирање на MySQL, Python или Nginx на серверот. Со една команда (`docker compose up`) целиот стек е во воздух, идентично без разлика дали се работи за локален компјутер, VPS или cloud сервер.

Во продолжение е објаснета конфигурацијата на Docker контејнерите, улогата на Nginx како reverse proxy кој ги насочува барањата кон точниот сервис, како и насоки за продукциско одржување и решавање на чести проблеми.

<table data-view="cards"><thead><tr><th></th><th data-type="content-ref"></th></tr></thead><tbody><tr><td>Docker</td><td><a href="docker.md">docker.md</a></td></tr><tr><td>Nginx</td><td><a href="nginx.md">nginx.md</a></td></tr><tr><td>Продукција и одржување</td><td><a href="production.md">production.md</a></td></tr></tbody></table>
