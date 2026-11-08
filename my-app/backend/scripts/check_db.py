import sqlite3

for name in ("meta.db", "messages.db"):
    con = sqlite3.connect(name)
    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' order by name")]
    print(name, "->", tables)
    con.close()

con = sqlite3.connect("meta.db")
print("users:", list(con.execute("select username from users")))
print("teams:", list(con.execute("select name from teams")))
con.close()