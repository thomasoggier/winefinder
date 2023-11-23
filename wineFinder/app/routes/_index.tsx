
import { ActionFunction, LoaderFunction } from "@remix-run/node";
import { Form, useLoaderData } from "@remix-run/react";
import authenticator from "~/services/auth.server";
import { getMenuButton } from "~/services/menu.client";
import { defaultMenu, getMenu, hasMenuAccess } from "~/services/menu.server";

/**
 * check the user to see if there is an active session, if not
 * redirect to login page
 *
 * @param param0
 * @returns
 */
export let loader: LoaderFunction = async ({ request }) => {


  const access = hasMenuAccess(defaultMenu, 'profile', ['User']);
  console.log(access)
  const user = await authenticator.isAuthenticated(request, {
    failureRedirect: "/login",
  });
  console.log('1')
  const menu = getMenu(defaultMenu, ['User']);
  console.log('2')
  return {user, menu};
};

/**
 *  handle the logout request
 *
 * @param param0
 */
export const action: ActionFunction = async ({ request }) => {
  await authenticator.logout(request, { redirectTo: "/login" });
};



export default function DashboardPage() {
  const data = useLoaderData<typeof loader>();
  console.log(data);

  const menu = getMenuButton(data.menu);
  console.log(menu);


  return (
    <div style={{ fontFamily: "system-ui, sans-serif", lineHeight: "1.4" }}>
      <h1>Welcome to Remix Protected Dashboard</h1>
      {menu}
      <Form method="post">
        <button>Log Out</button>
      </Form>
    </div>
  );
}