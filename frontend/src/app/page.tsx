import { redirect } from "next/navigation";

// The app's home is the upload screen; /deals/new sends visitors who aren't
// signed in to /login first.
export default function Home() {
  redirect("/deals/new");
}
