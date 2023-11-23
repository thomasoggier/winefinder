import authenticator from "~/services/auth.server";
import { LoaderFunction } from "@remix-run/node";

export let loader: LoaderFunction = async ({ request }) => {
  return await authenticator.isAuthenticated(request, {
    failureRedirect: "/welldone",
  });
};
export default function testPage() {
    return (<div>
        <h1>
            Hello user!
        </h1>
    </div>)
}