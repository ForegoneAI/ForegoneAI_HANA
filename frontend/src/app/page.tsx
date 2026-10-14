import { redirect } from "next/navigation";

// The app's home is the deal list; /deals sends visitors who aren't signed
// in to /login first.
export default function Home() {
  redirect("/deals");
}
