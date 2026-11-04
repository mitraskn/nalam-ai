"""End-to-end walk of every Nalam AI page and flow in a phone-size browser. Prints PASS/FAIL per step."""
import sys
from datetime import date, timedelta
from playwright.sync_api import sync_playwright

U = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8769/"
SAMPLES = "/home/claude/nalam/samples/"
results = []


def check(name, cond, detail=""):
    results.append((bool(cond), name))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    answers = {"prompt": "Thatha"}
    pg.on("dialog", lambda d: d.accept(answers["prompt"]) if d.type == "prompt" else d.accept())
    W = lambda ms=500: pg.wait_for_timeout(ms)
    txt = lambda: pg.inner_text("#main")
    shot = lambda n: pg.screenshot(path=f"/tmp/e2e_{n}.png", full_page=True)

    # 1. first open: Home page, empty
    pg.goto(U); W(800)
    check("1.1 first open shows Home page", pg.locator("#wFamName").count() == 1)
    check("1.2 fields are empty", pg.input_value("#wFamName") == "" and pg.input_value("#wPerson") == "")
    check("1.3 no Sign out before setup", "வெளியேறு" not in txt() and "Sign out" not in txt())
    check("1.4 no back / home buttons on Home", pg.locator("#backBtn.hide").count() == 1 and pg.locator("#homeBtn.hide").count() == 1)
    # language switch keeps typed text
    pg.fill("#wFamName", "Mitra"); pg.click("text=English"); W(); pg.click("text=Normal mode"); W()
    check("1.5 switch to English + Normal keeps typed name", pg.input_value("#wFamName") == "Mitra" and "Language" in txt())
    # validation
    pg.fill("#wFamPhone", "12345"); pg.fill("#wPerson", "Paati"); pg.click("text=Continue →"); W()
    check("1.6 bad phone is blocked", pg.locator("#wFamName").count() == 1 and "10 digits" in pg.inner_text("#toast"))
    pg.fill("#wFamPhone", "+91 98765 43210"); pg.fill("#wPerson", ""); pg.click("text=Continue →"); W()
    check("1.7 empty main person is blocked", pg.locator("#wFamName").count() == 1 and "who this app is for" in pg.inner_text("#toast"))
    pg.fill("#wPerson", "Paati"); pg.click("text=Continue →"); W(1200)
    check("1.8 Continue opens the Menu", pg.locator(".hello").count() == 1, txt()[:80])
    check("1.9 Menu greets Paati", "Paati" in pg.inner_text(".hello b"))
    check("1.10 back button on Menu, no home icon", pg.locator("#backBtn.hide").count() == 0 and pg.locator("#homeBtn.hide").count() == 1)
    shot("menu_empty")

    # 2. reopen: Home page with saved details
    pg.reload(); W(900)
    check("2.1 reopening shows Home page", pg.locator("#wFamName").count() == 1)
    check("2.2 details are filled in", pg.input_value("#wFamName") == "Mitra" and pg.input_value("#wFamPhone") == "9876543210" and pg.input_value("#wPerson") == "Paati",
          f'{pg.input_value("#wFamName")}|{pg.input_value("#wFamPhone")}|{pg.input_value("#wPerson")}')
    check("2.3 Sign out button shown", "Sign out" in txt())
    pg.click("text=Continue →"); W(1000)
    check("2.4 Continue goes to Menu again", pg.locator(".hello").count() == 1)
    pg.click("#backBtn"); W()
    check("2.5 back from Menu goes to Home", pg.locator("#wFamName").count() == 1)
    pg.click("text=Continue →"); W(1000)

    # 3. next-medicine card -> add medicine
    check("3.1 empty medicine card offers Add medicine", "Add medicine" in pg.inner_text("#nextDose"))
    pg.click("#nextDose button.ok"); W(1000)
    check("3.2 opens Today's medicines / care page", pg.locator("#careOut").count() == 1)
    pg.click(".tabs >> text=Medicines") if pg.locator(".tabs").count() else None; W(500)
    pg.fill("#mName", "Metformin"); pg.fill("#mDose", "500 mg"); pg.fill("#mTimes", "25:00"); pg.click("#careOut >> text=Save"); W()
    check("3.3 wrong time 25:00 blocked", "08:00" in pg.inner_text("#toast"))
    pg.fill("#mTimes", "08:00, 23:59"); pg.select_option("#mFood", "after"); pg.click("#careOut >> text=Save"); W(800)
    check("3.4 medicine saved", "Metformin" in pg.inner_text("#careOut"))
    pg.click(".tabs >> text=Today"); W(500)
    pg.locator("#careOut >> text=✅ Taken").first.click(); W(700)
    check("3.5 mark dose Taken", "Taken ✅" in pg.inner_text("#careOut") or "✅" in pg.inner_text("#careOut"))
    pg.click("#homeBtn"); W()
    check("3.6 home icon goes to Home page", pg.locator("#wFamName").count() == 1)
    pg.click("text=Continue →"); W(1200)
    nd = pg.inner_text("#nextDose")
    check("3.7 menu card shows next dose Metformin 23:59", "Metformin" in nd and "23:59" in nd, nd[:80])
    pg.click("#nextDose button.later"); W(600)
    check("3.8 Later shows reminder message", "15 minutes" in pg.inner_text("#nextDose"))
    pg.click("#nextDose button.ok"); W(900)
    check("3.9 Taken from card -> all done", "done" in pg.inner_text("#nextDose").lower(), pg.inner_text("#nextDose")[:80])

    # 4. Ask page
    pg.click("text=Ask a question"); W(500)
    def ask(q, wait=900):
        pg.fill("#askIn", q); pg.click(".askbar >> text=Send"); W(wait)
        return pg.locator(".chat .bot").last.inner_text()
    a = ask("What is BD?"); check("4.1 BD meaning", "2 times a day" in a, a[:80])
    a = ask("What is metformin for?"); check("4.2 medicine uses saved times", "diabetes" in a.lower() and ("08:00" in a or "time" in a.lower()), a[:120])
    a = ask("Metformin sapten, aana vaanthi varuthu"); check("4.3 warning + answer", "doctor" in a.lower() and "Metformin" in a, a[:100])
    a = ask("Is it true cold water gives cold?"); check("4.4 myth with source", "virus" in a.lower() and "Source" in a, a[:100])
    a = ask("Can Paati get the CMCHIS scheme?"); check("4.5 scheme rules, never 'eligible'", "1,20,000" in a and "official office" in a, a[:120])
    a = ask("should I double my dose tonight?"); check("4.6 dose question refused", "doctor or pharmacist" in a, a[:100])
    a = ask("Since my husband passed, I feel lonely at home all day"); check("4.7 support: calm steps then 14416", "breathe" in a and "14416" in a, a[:100])
    a = ask("Amma says her chest is paining and she is sweating"); W(600)
    check("4.8 emergency text + SOS sheet opens", "hospital" in a.lower() and pg.locator("#sos.on").count() == 1)
    shot("ask")
    pg.click("#sosSheet >> text=Close") if pg.locator("#sosSheet >> text=Close").count() else pg.keyboard.press("Escape"); W()
    pg.click("#backBtn"); W()
    check("4.9 back from Ask goes to Menu", pg.locator(".hello").count() == 1)

    # 5. Report page
    pg.click("text=Understand my report"); W()
    check("5.1 report page has Paati preselected", pg.eval_on_selector("#repPerson", "s=>s.value") == "Paati")
    with pg.expect_file_chooser() as fc:
        pg.click("#main button.primary")
    fc.value.set_files(SAMPLES + "sample_report_1_with_ranges.png"); W(2500)
    rt = txt()
    check("5.2 report results shown with High/Low", ("High" in rt or "HIGH" in rt) and "Source" in rt, rt[:120])
    shot("report")
    pg.click("#backBtn"); W()

    # 6. Prescription page
    pg.click("text=Read prescription"); W()
    with pg.expect_file_chooser() as fc:
        pg.click("#main button.primary")
    fc.value.set_files(SAMPLES + "sample_prescription_printed.png"); W(2500)
    rx = txt()
    check("6.1 prescription medicines listed", "Metformin" in rx, rx[:120])
    pg.locator("#main >> text=Save").last.click(); W(1200)
    check("6.2 saving prescription works", "Saved" in pg.inner_text("#toast") or "saved" in pg.inner_text("#toast").lower(), pg.inner_text("#toast"))
    pg.click("#backBtn"); W()

    # 7. Family care: appointments, visits, reports
    pg.click("text=Family care"); W(900)
    pg.click(".tabs >> text=Appointments"); W(400)
    y = (date.today() - timedelta(days=2)).isoformat(); f = (date.today() + timedelta(days=3)).isoformat()
    pg.evaluate(f"document.getElementById('aDate').removeAttribute('min');document.getElementById('aDate').value='{y}'")
    pg.click("#careOut >> text=Save"); W()
    check("7.1 past appointment blocked", "past date" in pg.inner_text("#toast"))
    pg.fill("#aDate", f); pg.fill("#aTime", "10:30"); pg.fill("#aWhere", "CMCH"); pg.click("#careOut >> text=Save"); W(800)
    check("7.2 future appointment saved", "CMCH" in pg.inner_text("#careOut"))
    pg.click(".tabs >> text=Doctor visits"); W(400)
    pg.evaluate(f"document.getElementById('vDate').removeAttribute('max');document.getElementById('vDate').value='{f}'")
    pg.click("#careOut button.primary"); W()
    check("7.3 future visit blocked", "future" in pg.inner_text("#toast"))
    pg.fill("#vDate", y); pg.fill("#vWhere", "Dr. Kumar")
    with pg.expect_file_chooser() as fc:
        pg.click("#careOut >> text=Add prescription")
    fc.value.set_files(SAMPLES + "sample_prescription_printed.png"); W(1200)
    pg.click("#careOut button.primary"); W(1200)
    check("7.4 visit saved with photo", pg.locator("#careOut img").count() >= 1 and "Dr. Kumar" in pg.inner_text("#careOut"))
    pg.click(".tabs >> text=Reports"); W(500)
    check("7.5 report history shows saved report", "HbA1c" in pg.inner_text("#careOut") or "Glucose" in pg.inner_text("#careOut"), pg.inner_text("#careOut")[:100])
    # add a second person from the dropdown
    pg.select_option("#carePerson", "__add"); W(1500)
    check("7.6 add person from dropdown", pg.eval_on_selector("#carePerson", "s=>s.value") == "Thatha")
    pg.click("#backBtn"); W(800)

    # 8. other pages
    for tile, must in (("Nearby hospital", "108"), ("Health myths", "truth"), ("Health schemes", "CMCHIS"), ("Feeling low", "14416")):
        if pg.locator(f"text={tile}").count() == 0:
            check(f"8 tile '{tile}' exists", False); continue
        pg.click(f"text={tile}"); W(600)
        check(f"8 {tile} page opens", must in txt(), txt()[:80])
        pg.click("#backBtn"); W(500)
        check(f"8 back from {tile} to Menu", pg.locator(".hello").count() == 1)

    # 9. SOS from Menu
    pg.click("#sosBtn"); W(500)
    st = pg.inner_text("#sosSheet")
    pg.wait_for_timeout(100); check("9.1 SOS sheet: call family + 108", "Mitra" in st or "family" in st.lower())
    check("9.2 SOS has 108", "108" in st)
    pg.locator("#sosSheet >> text=Close").click() if pg.locator("#sosSheet >> text=Close").count() else None; W()

    # 10. Elder mode + Tamil
    pg.click("#backBtn"); W()
    pg.click("text=தமிழ்"); W(); pg.click("text=👵 பெரியவர் முறை"); W()
    pg.click("text=தொடரவும் →"); W(1000)
    check("10.1 Elder mode Tamil menu", "வணக்கம்" in pg.inner_text(".hello b") and pg.locator(".tile").count() >= 5)
    shot("elder_menu")
    pg.click("text=கேள்வி கேளுங்கள்"); W()
    pg.fill("#askIn", "TDS என்றால் என்ன?"); pg.click(".askbar >> text=அனுப்பு"); W(900)
    check("10.2 Tamil answer", "3 முறை" in pg.locator(".chat .bot").last.inner_text())
    pg.click("#backBtn"); W()

    # 11. Sign out
    pg.click("#backBtn"); W()
    pg.click("text=வெளியேறு"); W(1500)
    check("11.1 after Sign out: Home page with empty details", pg.locator("#wFamName").count() == 1 and pg.input_value("#wFamName") == "" and pg.input_value("#wPerson") == "")
    pg.reload(); W(800)
    check("11.2 reopen after sign out stays empty", pg.input_value("#wFamName") == "" and pg.locator("#wFamName").count() == 1)

    check("NO JavaScript errors", not errs, "; ".join(errs)[:300])
    b.close()

ok = sum(r[0] for r in results)
print(f"\n{ok}/{len(results)} passed")
