/**
 * Firestore security rules test — 6a Social.
 *
 * Runs against the Firestore emulator (never production). Exercises every
 * acceptance-criterion-6 behavior from spec.md: read only as group member,
 * write only your own result doc in valid ranges, no editing others,
 * constrained group join.
 *
 * Run:
 *   npx firebase-tools emulators:exec --only firestore "node rules.test.js"
 * (from this directory — firebase.json here points at ../firestore.rules)
 */
const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertSucceeds,
  assertFails,
} = require('@firebase/rules-unit-testing');
const {
  doc,
  setDoc,
  updateDoc,
  getDoc,
  getDocs,
  collection,
  query,
  where,
  serverTimestamp,
} = require('firebase/firestore');

let passed = 0;
let failed = 0;

async function check(name, fn) {
  try {
    await fn();
    passed++;
    console.log(`  ok - ${name}`);
  } catch (e) {
    failed++;
    console.error(`  FAIL - ${name}`);
    console.error(`    ${e.message}`);
  }
}

async function main() {
  const testEnv = await initializeTestEnvironment({
    projectId: 'demo-mindmeld-rules-test',
    firestore: {
      rules: fs.readFileSync(path.resolve(__dirname, '../firestore.rules'), 'utf8'),
      host: '127.0.0.1',
      port: 8080,
    },
  });

  await testEnv.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, 'users/alice'), { displayName: 'Alice', createdAt: new Date(), groupIds: [] });
    await setDoc(doc(db, 'users/bob'), { displayName: 'Bob', createdAt: new Date(), groupIds: [] });
  });

  const alice = testEnv.authenticatedContext('alice').firestore();
  const bob = testEnv.authenticatedContext('bob').firestore();
  const anon = testEnv.unauthenticatedContext().firestore();

  // ---- users/{uid} ----
  await check('unauthenticated cannot read a profile', async () => {
    await assertFails(getDoc(doc(anon, 'users/alice')));
  });
  await check('a user can create their own profile', async () => {
    await assertSucceeds(
      setDoc(doc(alice, 'users/alice'), {
        displayName: 'Alice',
        createdAt: serverTimestamp(),
        groupIds: [],
      }),
    );
  });
  await check("a user cannot write another user's profile", async () => {
    await assertFails(setDoc(doc(bob, 'users/alice'), { displayName: 'Not Alice' }, { merge: true }));
  });

  // ---- users/{uid} — 6b notification fields ----
  await check('a user can opt into notifications with NO displayName at all', async () => {
    const dave = testEnv.authenticatedContext('dave').firestore();
    await assertSucceeds(
      setDoc(doc(dave, 'users/dave'), {
        fcmToken: 'tok-dave-1', notifLang: 'en', timezone: 'Asia/Kolkata',
        notifPendingAction: 'subscribe', notifUpdatedAt: serverTimestamp(),
      }),
    );
  });
  await check('a user can update just fcmToken without resending displayName', async () => {
    await assertSucceeds(
      setDoc(doc(alice, 'users/alice'), {
        fcmToken: 'tok-alice-1', notifPendingAction: 'subscribe', notifUpdatedAt: serverTimestamp(),
      }, { merge: true }),
    );
  });
  await check('unsubscribe: fcmToken/notifLang can be cleared to null', async () => {
    await assertSucceeds(
      setDoc(doc(alice, 'users/alice'), {
        fcmToken: null, notifLang: null, notifPendingAction: 'unsubscribe', notifUpdatedAt: serverTimestamp(),
      }, { merge: true }),
    );
  });
  await check('notifLang must be en or hi-en', async () => {
    await assertFails(
      setDoc(doc(alice, 'users/alice'), { notifLang: 'fr' }, { merge: true }),
    );
  });
  await check('notifPendingAction must be subscribe/unsubscribe/null', async () => {
    await assertFails(
      setDoc(doc(alice, 'users/alice'), { notifPendingAction: 'do-it-now' }, { merge: true }),
    );
  });
  await check('notifUpdatedAt cannot be backdated', async () => {
    await assertFails(
      setDoc(doc(alice, 'users/alice'), { notifUpdatedAt: new Date('2020-01-01') }, { merge: true }),
    );
  });
  await check("a user still cannot write another user's notification fields", async () => {
    await assertFails(
      setDoc(doc(bob, 'users/alice'), { fcmToken: 'stolen' }, { merge: true }),
    );
  });

  // ---- groups/{groupId} create ----
  await check('unauthenticated cannot create a group', async () => {
    await assertFails(
      setDoc(doc(anon, 'groups/g1'), {
        name: 'G', code: 'ABC123', createdBy: 'alice', memberUids: ['alice'], createdAt: serverTimestamp(),
      }),
    );
  });
  await check('creator can create a group with memberUids=[self]', async () => {
    await assertSucceeds(
      setDoc(doc(alice, 'groups/g1'), {
        name: 'G', code: 'ABC123', createdBy: 'alice', memberUids: ['alice'], createdAt: serverTimestamp(),
      }),
    );
  });
  await check('cannot create a group claiming someone else as creator', async () => {
    await assertFails(
      setDoc(doc(bob, 'groups/g2'), {
        name: 'G2', code: 'ZZZ999', createdBy: 'alice', memberUids: ['bob'], createdAt: serverTimestamp(),
      }),
    );
  });
  await check("cannot create a group whose memberUids isn't just yourself", async () => {
    await assertFails(
      setDoc(doc(bob, 'groups/g3'), {
        name: 'G3', code: 'YYY888', createdBy: 'bob', memberUids: ['bob', 'alice'], createdAt: serverTimestamp(),
      }),
    );
  });

  // ---- codes/{code} ----
  await check('creator can create the matching join code atomically', async () => {
    await assertSucceeds(setDoc(doc(alice, 'codes/ABC123'), { groupId: 'g1' }));
  });
  await check("a non-creator cannot create a code pointing at someone else's group", async () => {
    await assertFails(setDoc(doc(bob, 'codes/HACKED'), { groupId: 'g1' }));
  });
  await check('a code is immutable once created', async () => {
    await assertFails(updateDoc(doc(alice, 'codes/ABC123'), { groupId: 'g999' }));
  });
  await check('anyone signed in can resolve a code (get)', async () => {
    await assertSucceeds(getDoc(doc(bob, 'codes/ABC123')));
  });

  // ---- groups/{groupId} get/list ----
  await check('a non-member CAN get a single group doc by id', async () => {
    await assertSucceeds(getDoc(doc(bob, 'groups/g1')));
  });
  await check("a non-member's arrayContains-self query returns only their own groups (list rule)", async () => {
    await assertSucceeds(getDocs(query(collection(bob, 'groups'), where('memberUids', 'array-contains', 'bob'))));
  });

  // ---- join flow ----
  await check('a user can add ONLY their own uid to memberUids', async () => {
    await assertSucceeds(updateDoc(doc(bob, 'groups/g1'), { memberUids: ['alice', 'bob'] }));
  });
  await check("a user cannot add someone else's uid while joining", async () => {
    await testEnv.withSecurityRulesDisabled(async (ctx) => {
      await setDoc(doc(ctx.firestore(), 'groups/g4'), {
        name: 'G4', code: 'JJJ111', createdBy: 'alice', memberUids: ['alice'], createdAt: new Date(),
      });
    });
    await assertFails(updateDoc(doc(bob, 'groups/g4'), { memberUids: ['alice', 'bob', 'carol'] }));
  });
  await check('a member cannot remove another member while joining', async () => {
    await testEnv.withSecurityRulesDisabled(async (ctx) => {
      await setDoc(doc(ctx.firestore(), 'groups/g5'), {
        name: 'G5', code: 'KKK222', createdBy: 'alice', memberUids: ['alice'], createdAt: new Date(),
      });
    });
    await assertFails(updateDoc(doc(bob, 'groups/g5'), { memberUids: ['bob'] }));
  });

  // ---- results/{uid} ----
  const today = '2026-07-06';
  await check('a member can create their own result with valid fields', async () => {
    await assertSucceeds(
      setDoc(doc(bob, `groups/g1/days/${today}/results/bob`), {
        uid: 'bob', displayName: 'Bob', outcome: 'win', guessesUsed: 5, par: 6,
        scoreVsPar: -1, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check('a non-member cannot create a result in that group', async () => {
    await testEnv.withSecurityRulesDisabled(async (ctx) => {
      await setDoc(doc(ctx.firestore(), 'users/carol'), { displayName: 'Carol', createdAt: new Date(), groupIds: [] });
    });
    const carol = testEnv.authenticatedContext('carol').firestore();
    await assertFails(
      setDoc(doc(carol, `groups/g1/days/${today}/results/carol`), {
        uid: 'carol', displayName: 'Carol', outcome: 'win', guessesUsed: 5, par: 6,
        scoreVsPar: -1, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check('a member cannot write a result doc for another uid', async () => {
    await assertFails(
      setDoc(doc(bob, `groups/g1/days/${today}/results/alice`), {
        uid: 'alice', displayName: 'Alice', outcome: 'win', guessesUsed: 5, par: 6,
        scoreVsPar: -1, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check('displayName must match your own profile (no forging)', async () => {
    await assertFails(
      setDoc(doc(alice, `groups/g1/days/${today}/results/alice`), {
        uid: 'alice', displayName: 'Not Alice', outcome: 'win', guessesUsed: 5, par: 6,
        scoreVsPar: -1, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check('guessesUsed out of range is rejected', async () => {
    await assertFails(
      setDoc(doc(alice, `groups/g1/days/${today}/results/alice`), {
        uid: 'alice', displayName: 'Alice', outcome: 'win', guessesUsed: 0, par: 6,
        scoreVsPar: -6, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check('par must be > 0', async () => {
    await assertFails(
      setDoc(doc(alice, `groups/g1/days/${today}/results/alice`), {
        uid: 'alice', displayName: 'Alice', outcome: 'win', guessesUsed: 5, par: 0,
        scoreVsPar: 5, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check('outcome must be win or loss', async () => {
    await assertFails(
      setDoc(doc(alice, `groups/g1/days/${today}/results/alice`), {
        uid: 'alice', displayName: 'Alice', outcome: 'draw', guessesUsed: 5, par: 6,
        scoreVsPar: -1, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check('a result is CREATE-ONLY — overwriting your own result fails', async () => {
    await assertFails(
      setDoc(doc(bob, `groups/g1/days/${today}/results/bob`), {
        uid: 'bob', displayName: 'Bob', outcome: 'loss', guessesUsed: 12, par: 6,
        scoreVsPar: 6, lang: 'en', finishedAt: serverTimestamp(),
      }),
    );
  });
  await check("a member can list/read the day's results", async () => {
    await assertSucceeds(getDocs(collection(bob, `groups/g1/days/${today}/results`)));
  });
  await check('a non-member cannot read the day\'s results (spoiler safety at the rules layer)', async () => {
    const carol = testEnv.authenticatedContext('carol').firestore();
    await assertFails(getDocs(collection(carol, `groups/g1/days/${today}/results`)));
  });

  // ---- default deny ----
  await check('an unlisted collection is denied by default', async () => {
    await assertFails(setDoc(doc(alice, 'somethingElse/doc1'), { a: 1 }));
  });

  await testEnv.cleanup();

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
