import Link from "next/link";

import styles from "./page.module.css";

export default function Home() {
  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>Collaborative canvas</h1>
        <p>
          Open a room in two browser tabs and drag a rectangle in one of them.
        </p>
        <Link className={styles.primary} href="/r/demo">
          Open the demo room
        </Link>
      </main>
    </div>
  );
}
