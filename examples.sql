CREATE DATABASE IF NOT EXISTS Math_App;



/* Create table in Math_App database using alternate primary key specification method */
CREATE TABLE IF NOT EXISTS Math_User (
    Id INT AUTO_INCREMENT,
    Name VARCHAR(16) NOT NULL,
    PRIMARY KEY (Id)
); 	 	


/* Modify existing table to add a column */
ALTER TABLE Math_User 
ADD COLUMN Favorite_Color VARCHAR(16);

/* Modify existing table to remove a column and its associated data
ALTER TABLE Math_User
DROP COLUMN Favorite_Color;
*/

/* single row insertion */
INSERT INTO Math_User (Name, Favorite_Color) 
VALUES ('Lia', 'Orange');

/* Insert row with partial data specified */
INSERT INTO Math_User (Name)
VALUES ('Bill');

/* Multi row insertion */
INSERT INTO Math_User (Name, Favorite_Color) 
VALUES ("Ava", "Purple"), ('Ella', "Pink"), ('Parker', 'White'), ('BingBong', 'Underwear');

/* read all data from table */
SELECT 
    *
FROM
    Math_User;

/* select all rows and two columns from table */ 
SELECT 
    id, name
FROM
    Math_User;

/* select one row and one column from table */
SELECT 
    favorite_color
FROM
    Math_User
WHERE
    name = 'Ava';
    
/* sort by name ascending */
SELECT 
    *
FROM
    Math_User
ORDER BY
	name ASC;
   
/* return data in descending order */
SELECT 
    *
FROM
    Math_User
ORDER BY
	Favorite_Color DESC;
    
/* sorting multiple columns, each asc/desc separately */
    SELECT 
    *
FROM
    Math_User
ORDER BY
	name ASC, Favorite_Color ASC;


/* Change existing row data */
UPDATE Math_User 
SET 
    Favorite_Color = 'Left Tackle'
WHERE
    Id = 79;
    
COMMIT;

/* Delete a row */
DELETE FROM Math_User 
WHERE
    Id = 178;

/* Results child table with foreign key to parent table (Math_User) */
/* the FK will auto update on changes and delete associated child tables if the parent is delete */
CREATE TABLE IF NOT EXISTS Results (
    Id INT PRIMARY KEY AUTO_INCREMENT,
    Score INT NOT NULL,
    Tries INT NOT NULL,
    Example_Enum ENUM('Banana', 'Apple', 'Pepper'),
    User_Id INT NOT NULL,
    FOREIGN KEY (User_Id)
        REFERENCES Math_User (Id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

/* Insert Results row where user is Lia (id=1) */
INSERT INTO Results (Score, Tries, Example_Enum, User_Id)
VALUES (100, 101, 'Apple', 1);

/* Select values from table and stored in variable @TempId */
SELECT 
    Id
FROM
    Math_User
WHERE
    name = 'BingBong' INTO @TempId;

/* Insert row in Resultes using the variable */
INSERT INTO Results (Score, Tries, User_Id)
VALUES (3, 26000, @TempId);

/* display table definitions */
SHOW tables;
DESC user;
DESC result;

SELECT 
    *
FROM
    Results;

/* Inner join to display results with user name */

SELECT 
    Math_User.name, Results.Score, Results.Tries, Results.Example_Enum
FROM
    Results
        INNER JOIN
    Math_User ON (Results.User_Id = Math_User.Id);

/* return a JSON string */
SELECT
	json_arrayagg(JSON_OBJECT('Id', Id, 'Name', Name, 'Favorite_Color', Favorite_Color))
FROM
	Math_User;
/* ORDER BY Name desc, Favorite_Color asc, Id desc; */
    
/* DROP TABLE deletes tables and its data definition */
/*DROP TABLE Math_User;

DROP TABLE Results;
*/
/* DROP DATABASE deletes the whole database, this is the BIG HAMMER so be careful */
/*DROP DATABASE Math_App;
*/

/* TRUNCATE deletes all data from table, but retains its defintion */
/*TRUNCATE Math_User;
*/

SELECT @@GLOBAL.transaction_isolation, @@GLOBAL.transaction_read_only;
SELECT @@SESSION.transaction_isolation, @@SESSION.transaction_read_only;

SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

SHOW STATUS WHERE `variable_name` = 'Threads_connected';

show session status;

show global status;