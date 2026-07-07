/**
 * Full create-group integration test — sign-in -> users/{uid} write ->
 * groups/{groupId} write -> codes/{code} write -> a second user joins.
 *
 * Unlike rules.test.js (which uses @firebase/rules-unit-testing's
 * authenticatedContext to SIMULATE an already-signed-in uid), this test
 * drives the REAL client SDK against the Auth + Firestore emulators —
 * signInAnonymously() included — so the exact sequence app code runs is
 * what gets exercised, not an approximation of it.
 *
 * This test exists because of a real production bug (2026-07-07): the
 * original createGroup() wrote groups/{groupId} and codes/{code} together
 * in ONE atomic WriteBatch. The codes/{code} create rule does a get() on
 * the group doc to check ownership, and Firestore does NOT let a batched
 * write's rule evaluation see a sibling write from the SAME batch — so
 * that get() saw a non-existent group and every single create failed with
 * permission-denied (misread by the retry loop as "code collision", so it
 * silently retried 5x before finally erroring). The fix: write the group
 * doc first and await it, THEN write the code doc as a separate operation.
 * This test pins that sequential pattern and would fail again if someone
 * reintroduces the batched version.
 *
 * Run (from repo root, needs JDK 21+):
 *   firebase-tests/node_modules/.bin/firebase emulators:exec --project demo-mindmeld-rules-test \
 *     --only firestore,auth "node firebase-tests/create_group_flow.test.js"
 */
const fs = require('fs');
const path = require('path');
const { initializeApp, deleteApp } = require('firebase/app');
const { getAuth, connectAuthEmulator, signInAnonymously, signOut } = require('firebase/auth');
const {
  getFirestore,
  connectFirestoreEmulator,
  doc,
  collection,
  setDoc,
  getDoc,
  writeBatch,
  updateDoc,
  serverTimestamp,
} = require('firebase/firestore');
const { initializeTestEnvironment } = require('@firebase/rules-unit-testing');

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

/** Generates a Firebase app + connected Auth/Firestore pair, one per "device". */
function makeClient(appName) {
  const app = initializeApp(
    { apiKey: 'fake-api-key', projectId: 'demo-mindmeld-rules-test' },
    appName,
  );
  const auth = getAuth(app);
  connectAuthEmulator(auth, 'http://127.0.0.1:9099', { disableWarnings: true });
  const db = getFirestore(app);
  connectFirestoreEmulator(db, '127.0.0.1', 8080);
  return { app, auth, db };
}

/** Mirrors _LiveSocialClient.createGroup's sequential (non-batched) write. */
async function createGroupSequential(db, uid, name, code) {
  const groupRef = doc(collection(db, 'groups'));
  await setDoc(groupRef, {
    name,
    code,
    createdBy: uid,
    memberUids: [uid],
    createdAt: serverTimestamp(),
  });
  await setDoc(doc(db, 'codes', code), { groupId: groupRef.id });
  return groupRef.id;
}

/** The OLD, buggy pattern — kept only to prove it still fails (regression guard). */
async function createGroupBatched(db, uid, name, code) {
  const groupRef = doc(collection(db, 'groups'));
  const codeRef = doc(db, 'codes', code);
  const batch = writeBatch(db);
  batch.set(groupRef, {
    name, code, createdBy: uid, memberUids: [uid], createdAt: serverTimestamp(),
  });
  batch.set(codeRef, { groupId: groupRef.id });
  await batch.commit();
  return groupRef.id;
}

async function main() {
  // A rules-unit-testing env is used ONLY to seed nothing and clear data
  // between runs; the actual assertions run through the real client SDK.
  const testEnv = await initializeTestEnvironment({
    projectId: 'demo-mindmeld-rules-test',
    firestore: {
      rules: fs.readFileSync(path.resolve(__dirname, '../firestore.rules'), 'utf8'),
      host: '127.0.0.1',
      port: 8080,
    },
  });
  await testEnv.clearFirestore();

  const alice = makeClient('alice-app');
  const bob = makeClient('bob-app');

  let aliceUid;
  let bobUid;
  let groupId;
  const code = 'FLOW01';

  await check('anonymous sign-in resolves to a uid (Auth emulator)', async () => {
    const cred = await signInAnonymously(alice.auth);
    aliceUid = cred.user.uid;
    if (!aliceUid) throw new Error('no uid returned');
  });

  await check("alice's profile doc can be created (users/{uid})", async () => {
    await setDoc(doc(alice.db, 'users', aliceUid), {
      displayName: 'Alice', createdAt: serverTimestamp(), groupIds: [],
    });
  });

  await check('full sequential create-group flow succeeds end to end', async () => {
    groupId = await createGroupSequential(alice.db, aliceUid, 'Office Crew', code);
    const snap = await getDoc(doc(alice.db, 'groups', groupId));
    if (!snap.exists()) throw new Error('group doc missing after create');
    const codeSnap = await getDoc(doc(alice.db, 'codes', code));
    if (!codeSnap.exists() || codeSnap.data().groupId !== groupId) {
      throw new Error('code doc missing or points at the wrong group');
    }
  });

  await check('REGRESSION GUARD: the old batched write pattern still fails', async () => {
    let threw = false;
    try {
      await createGroupBatched(alice.db, aliceUid, 'Should Not Exist', 'BATCH1');
    } catch (e) {
      threw = true;
    }
    if (!threw) {
      throw new Error(
        'batched group+code write unexpectedly SUCCEEDED — if Firestore semantics changed, ' +
        'the sequential-write fix in social_client.dart may no longer be necessary, but this ' +
        'test (and the comment in createGroup()) need to be revisited, not silently left stale.',
      );
    }
  });

  await check('a second anonymous user can sign in, resolve the code, and join', async () => {
    const cred = await signInAnonymously(bob.auth);
    bobUid = cred.user.uid;
    await setDoc(doc(bob.db, 'users', bobUid), {
      displayName: 'Bob', createdAt: serverTimestamp(), groupIds: [],
    });

    const codeSnap = await getDoc(doc(bob.db, 'codes', code));
    if (!codeSnap.exists()) throw new Error('bob could not resolve the code');
    const joinedGroupId = codeSnap.data().groupId;

    const groupSnapBefore = await getDoc(doc(bob.db, 'groups', joinedGroupId));
    const membersBefore = groupSnapBefore.data().memberUids;

    await updateDoc(doc(bob.db, 'groups', joinedGroupId), {
      memberUids: [...membersBefore, bobUid],
    });

    const groupSnapAfter = await getDoc(doc(alice.db, 'groups', joinedGroupId));
    const membersAfter = groupSnapAfter.data().memberUids;
    if (!membersAfter.includes(aliceUid) || !membersAfter.includes(bobUid)) {
      throw new Error(`expected both members, got ${JSON.stringify(membersAfter)}`);
    }
  });

  await signOut(alice.auth).catch(() => {});
  await signOut(bob.auth).catch(() => {});
  await deleteApp(alice.app);
  await deleteApp(bob.app);
  await testEnv.cleanup();

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
