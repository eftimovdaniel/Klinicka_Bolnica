-- Додавање на колона за висина на насловната слика (px)
USE Klinicka_Bolnica_Stip;

ALTER TABLE Novosti ADD COLUMN slika_height VARCHAR(10) DEFAULT NULL;
