# Subword-collision scan report

K=15, threshold=0.2 (neighbor origin=english AND orthographically_similar -- see collision_scan.orthographically_similar's docstring for the exact formula). `*` marks a neighbor counted toward the score; `(e)`/`(h)` = english/hinglish origin.

## Calibration (known collision words)

| word | gloss | collision_score | n/K | top neighbors |
|---|---|---|---|---|
| daraa | scared | 0.200 | 3/15 | darren*(e), darr(h), darwin*(e), door(h), darpan(h), darling*(e), darwaza(h), doors(e), corridor(e), deewar(h), drawer(e), household(e), wardrobe(e), chadar(h), ghar(h) |
| accha | good | 0.200 | 3/15 | chachi(h), ace*(e), chacha(h), bachcha(h), chick(e), bachpan(h), pocha(h), ac(h), adams(e), angocha(h), chi*(e), chamcha(h), ana*(e), toddler(e), oct(e) |
| angocha | towel | 0.267 | 4/15 | angoor(h), pocha(h), bagicha(h), angoothi(h), accha(h), angutha(h), congo*(e), ncaa*(e), honda(e), anal*(e), andrea*(e), amanda(e), aug(e), broncos(e), vodka(e) |
| naukri | job | 0.000 | 0/15 | tokri(h), nauka(h), norfolk(e), nariyal(h), nau(h), bruce(e), kheer(h), nascar(e), barber(e), coconut(e), pakora(h), paneer(h), fisher(e), turkey(e), cookie(e) |
| sharbat | juice | 0.400 | 6/15 | sharm(h), sharon*(e), salwar(h), sharminda(h), sherman*(e), turban(h), syria*(e), kurt(e), shirt*(e), shirts*(e), murray(e), sheer(e), syrian*(e), tarbooz(h), qurbani(h) |
| seedha | straight | 0.267 | 4/15 | seed*(e), seedi(h), seeds*(e), root(e), ruth(e), stem(e), rooted(e), roots(e), plant(e), stems(e), plants(e), tree*(e), reed*(e), leaf(e), twig(e) |
| seena | chest | 0.267 | 4/15 | sees*(e), see*(e), seeing*(e), sight(e), looking(e), viewed(e), glance(e), lookin(e), looks(e), look(e), seen*(e), saw(e), kane(e), looked(e), viewing(e) |
| halwa | sweet | 0.333 | 5/15 | haldi(h), tawa(h), chawal(h), milwaukee*(e), lightly(e), lazy(e), halloween*(e), slim(e), mild(e), lahsun(h), pale*(e), holmes(e), sullivan(e), hahaha*(e), half*(e) |
| chashma | glasses | 0.267 | 4/15 | chamcha(h), chai(h), kamar(h), champ*(e), ash*(e), gum(e), tea(e), cough(e), powder(h), champagne*(e), chocolate(e), chad*(e), sugar(e), cheese(e), kheer(h) |
| junoon | passion | 0.467 | 7/15 | afternoon*(e), noon*(e), june*(e), jun*(e), twilight(e), juan*(e), jennifer(e), knox*(e), yesterday(e), tuesday(e), joan*(e), evening(e), shaam(h), lunch(e), sunday(e) |
| registan | desert | 0.400 | 6/15 | register*(e), registry*(e), registration*(e), registered*(e), ret(h), post office(h), rep*(e), post*(e), filing(e), record(e), filed(e), records(e), password(e), passport(e), documented(e) |
| jheel | lake | 0.333 | 5/15 | joel*(e), swing(e), jharu(h), heel*(e), swinging(e), jill*(e), jharna(h), tide(e), wheel*(e), dragging(e), crawl(e), spinning(e), twitch(e), sliding(e), chill*(e) |
| udaasi | sadness | 0.000 | 0/15 | udaas(h), desi(h), uber(e), ideal(e), alice(e), ace(e), elaichi(h), admire(e), philip(e), eleanor(e), idaho(e), fond(e), urad(h), ivy(e), leeds(e) |

## Full scan: 544 hinglish-sourced words, 211 >= threshold (0.2)

### Top 20 most severe

| word | gloss | collision_score | n/K | top neighbors |
|---|---|---|---|---|
| ande | eggs | 0.667 | 10/15 | andy*(e), andre*(e), andhera(h), and*(e), chhath(h), evan*(e), ate*(e), anne*(e), andrea*(e), ave*(e), unusually(e), aur(h), anymore*(e), unto(e), andrew*(e) |
| bank | bank | 0.667 | 10/15 | banks*(e), banking*(e), banker*(e), bankers*(e), financial*(e), finance*(e), cash(e), finances*(e), currency(e), financing*(e), treasury(e), fund(e), financially*(e), funds(e), panama*(e) |
| ganna | sugarcane | 0.667 | 10/15 | donna*(e), gaana(h), guinea*(e), quinn(e), finn*(e), dennis(e), ana*(e), dana*(e), cincinnati*(e), cannabis*(e), singing(e), shannon*(e), glenn*(e), khana(h), grain*(e) |
| hara | green | 0.667 | 10/15 | hart*(e), harper*(e), harold*(e), harvey*(e), harrison*(e), harry*(e), hamper*(e), ted(e), harm*(e), hating*(e), hurting(e), toh(h), haar(h), suffering(e), barack*(e) |
| heera | diamond | 0.667 | 10/15 | herbert*(e), ira*(e), jeera(h), hes*(e), harry*(e), surrey(e), sheer*(e), greene(e), sitara(h), sierra*(e), hiv(e), terry*(e), hebrew*(e), perry*(e), ferrari*(e) |
| ret | sand | 0.667 | 10/15 | reed*(e), rex*(e), rep*(e), rey*(e), rear*(e), res*(e), registan(h), leigh(e), reuters*(e), rubber(e), red*(e), reagan*(e), robert*(e), pitt(e), ted(e) |
| sandook | trunk | 0.667 | 10/15 | sand*(e), brooke*(e), brooks*(e), sandra*(e), sands*(e), sandy*(e), sanders*(e), pond*(e), samunder(h), trout(e), creek(e), pool*(e), reef(e), sink*(e), lake(e) |
| bua | aunt | 0.600 | 9/15 | bum*(e), bubble*(e), bravo*(e), blu(e), bewafa(h), burke*(e), bruno*(e), bubbles*(e), bucket*(e), gum(e), bud*(e), guinea(e), cue(e), bump*(e), goose(e) |
| mama | maternal uncle | 0.600 | 9/15 | mami(h), maa(h), mommy*(e), moms*(e), mothers(e), mom*(e), mum*(e), mother(e), madame*(e), grandma*(e), maternal*(e), emma*(e), dame*(e), mausi(h), dom(e) |
| mami | aunt | 0.600 | 9/15 | mama(h), mommy*(e), maa(h), moms*(e), mothers(e), mom*(e), mother(e), mum*(e), dame*(e), madame*(e), maternal*(e), grandma*(e), emma*(e), dom(e), mausi(h) |
| patli | bandage | 0.600 | 9/15 | patla(h), platter*(e), patches*(e), patch*(e), plate*(e), pat*(e), paste*(e), powder(h), patthi(h), pads*(e), peanut(e), peel*(e), pot*(e), patang(h), foil(e) |
| sharm | shyness | 0.600 | 9/15 | sharon*(e), shirt*(e), shawn*(e), shirts*(e), sharminda(h), sharbat(h), shoes*(e), turban(h), clothing(e), skirt*(e), wear*(e), shane*(e), shoe*(e), gown(e), dress(e) |
| tele | television | 0.600 | 9/15 | telegraph*(e), telephone*(e), cable*(e), phone(e), television*(e), transmission(e), channels*(e), tube*(e), channel*(e), cables*(e), broadcasting(e), broadcast(e), radio(h), phones(e), wireless*(e) |
| tinda | apple gourd | 0.600 | 9/15 | tampa*(e), tin*(e), tina*(e), tan*(e), tend*(e), teddy*(e), tory(e), tea*(e), tom(e), trent(e), tail(e), titli(h), todd*(e), linda*(e), tokri(h) |
| baingan | eggplant | 0.533 | 8/15 | baigan(h), bait*(e), bangkok*(e), bacon*(e), finn*(e), bin*(e), pork(e), baron*(e), bagicha(h), pan*(e), quinn*(e), burger(e), kangan(h), beef(e), congo(e) |
| chappal | slipper | 0.533 | 8/15 | papad(h), chapman*(e), chad*(e), kapda(h), papa*(e), cap*(e), patthi(h), pads*(e), capita*(e), caps*(e), padlock(e), parchhain(h), tapping*(e), patta(h), cheek(e) |
| comb | comb | 0.533 | 8/15 | comp*(e), combo*(e), cum*(e), colombia*(e), compression*(e), kamar(h), gum(e), columbia*(e), lib(e), congo*(e), dong(e), tampa(e), kamra(h), tom*(e), cuz(e) |
| darr | fear | 0.533 | 8/15 | darren*(e), darwin*(e), daraa(h), darling*(e), drawer*(e), darpan(h), dorothy(e), perry*(e), kurt(e), gardner*(e), andrew(e), larry*(e), lap(e), derby*(e), dheere(h) |
| gora | fair | 0.533 | 8/15 | gore*(e), gregory*(e), gerald*(e), greg(e), gop*(e), ghagra(h), grey(e), gary*(e), monroe(e), gordon*(e), cow(e), guinea(e), gosh*(e), laura*(e), jeera(h) |
| hing | asafoetida | 0.533 | 8/15 | ping*(e), hong*(e), hip*(e), fringe*(e), hips*(e), dong*(e), hamper(e), hang*(e), trunk(e), patang(h), honda*(e), honth(h), laung(h), bent(e), heel(e) |
