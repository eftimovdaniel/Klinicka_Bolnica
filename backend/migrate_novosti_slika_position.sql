-- Додавање на колона за позиција на слика во табелата Novosti
USE Klinicka_Bolnica_Stip;

ALTER TABLE Novosti ADD COLUMN slika_position VARCHAR(20) DEFAULT NULL;

