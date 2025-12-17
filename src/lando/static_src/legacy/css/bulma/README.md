### Bulma (Version: 1.0.4)

See [https://github.com/jgthms/bulma](https://github.com/jgthms/bulma).
This is a vendored copy of Bulma used for compiling our custom version of it
using the customization variables it provides via Dart Sass `@use` syntax.

### How to upgrade

1. Download the desired version from https://github.com/jgthms/bulma/releases
2. Extract the archive to a temporary location
3. Copy the `bulma.scss` file and the `sass` folder into this folder, replacing
   any existing files:
   ```bash
   cp bulma-x.x.x/bulma.scss ./
   cp -r bulma-x.x.x/sass ./
   ```
4. Update the version number at the top of this README.md file to match the version
   you downloaded.
5. Test the build with `lando collectstatic --clear --no-input`

### How to customize

Bulma 1.0+ uses Dart Sass modules. To customize Bulma variables, use the `@use`
syntax with the `with` clause in `lando.scss`:

```scss
@use "bulma/bulma" with (
  $primary: #0a84ff,
  $family-sans-serif: ('Fira Sans', Arial, sans-serif)
);
```

See the [official customization guide](https://bulma.io/documentation/customize/with-sass/)
for more details.
