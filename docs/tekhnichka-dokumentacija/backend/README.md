# Backend

Backend-от е срцето на целиот систем — FastAPI апликација напишана во Python која ја содржи сета бизнис логика, ги обработува барањата што доаѓаат од frontend-от, ги валидира внесените податоци и комуницира со базата. Целата логика е организирана по домени преку routers — посебни модули за лекари, пациенти, термини, апарати, новости, кариера, услуги, администрација и AI чат — секој изграден според иста, конзистентна структура која го прави кодот лесен за читање и одржување.

Во продолжение е објаснета внатрешната организација на backend-от, структурата и релациите во MySQL базата на податоци, конвенциите кои ги следат сите API endpoints, како и начинот на кој функционира вградениот AI асистент.

<table data-view="cards"><thead><tr><th></th><th data-type="content-ref"></th></tr></thead><tbody><tr><td>Преглед на backend</td><td><a href="../../backend/pregled.md">pregled.md</a></td></tr><tr><td>База на податоци</td><td><a href="../../backend/the_database.md">the_database.md</a></td></tr><tr><td>API</td><td><a href="../../backend/api/conventions.md">conventions.md</a></td></tr><tr><td>AI асистент</td><td><a href="../../backend/ai-assistant/overview.md">overview.md</a></td></tr><tr><td>Безбедност</td><td><a href="bezbednost-na-sistemot.md">bezbednost-na-sistemot.md</a></td></tr></tbody></table>
