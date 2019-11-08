<?php
/**
 * La configuration de base de votre installation WordPress.
 *
 * Ce fichier contient les réglages de configuration suivants : réglages MySQL,
 * préfixe de table, clés secrètes, langue utilisée, et ABSPATH.
 * Vous pouvez en savoir plus à leur sujet en allant sur
 * {@link http://codex.wordpress.org/fr:Modifier_wp-config.php Modifier
 * wp-config.php}. C’est votre hébergeur qui doit vous donner vos
 * codes MySQL.
 *
 * Ce fichier est utilisé par le script de création de wp-config.php pendant
 * le processus d’installation. Vous n’avez pas à utiliser le site web, vous
 * pouvez simplement renommer ce fichier en "wp-config.php" et remplir les
 * valeurs.
 *
 * @package WordPress
 */

// ** Réglages MySQL - Votre hébergeur doit vous fournir ces informations. ** //
/** Nom de la base de données de WordPress. */
define( 'DB_NAME', 'wp_database' );

/** Utilisateur de la base de données MySQL. */
define( 'DB_USER', 'wpuser' );

/** Mot de passe de la base de données MySQL. */
define( 'DB_PASSWORD', 'cgcde979z' );

/** Adresse de l’hébergement MySQL. */
define( 'DB_HOST', 'localhost' );

/** Jeu de caractères à utiliser par la base de données lors de la création des tables. */
define( 'DB_CHARSET', 'utf8mb4' );

/** Type de collation de la base de données.
  * N’y touchez que si vous savez ce que vous faites.
  */
define('DB_COLLATE', '');

/**#@+
 * Clés uniques d’authentification et salage.
 *
 * Remplacez les valeurs par défaut par des phrases uniques !
 * Vous pouvez générer des phrases aléatoires en utilisant
 * {@link https://api.wordpress.org/secret-key/1.1/salt/ le service de clefs secrètes de WordPress.org}.
 * Vous pouvez modifier ces phrases à n’importe quel moment, afin d’invalider tous les cookies existants.
 * Cela forcera également tous les utilisateurs à se reconnecter.
 *
 * @since 2.6.0
 */
define( 'AUTH_KEY',         ':^53fO.;n&.5C4680IEu>P xN={>)eC@tjsiFk-GWe5aa]h6IXqO:zuKcO[pw_CL' );
define( 'SECURE_AUTH_KEY',  'GiR~MH}2ZfPAgxCz[xz1F/tG$$1T}+jIwpaz3;jDYQ,v=3lJyX-rD.(b(ggA,-D?' );
define( 'LOGGED_IN_KEY',    'eBP4v/`1Z%TGkgP.[Jlza_|wUC.md{B efXmz(Q5~0P]a4M$7sup!m)a<&[9PR*E' );
define( 'NONCE_KEY',        '0[SU-q69+9Ud(hyemMbW#0hs3Td#G$<EnA,yCK qZKQd:>npB0xl(47zI50H+ZB6' );
define( 'AUTH_SALT',        'lPww+^YW560~t6 bW>O=[.&vF{]TNB>#CnX%Nb]1peXmW9&?g_d>_{e)o3K^0B#p' );
define( 'SECURE_AUTH_SALT', '6B&J ! DH)mS;B5[gXIL%!n|/yr.U<Z!g?Cvl &&vWOZR)d[0Ia9:ELcP#TGE<e1' );
define( 'LOGGED_IN_SALT',   'ie7p_0FJVH5xqtYTzAdi@J_l^]yN;g&:V{cfS[aq&O`5bFeh;MPRbEPyD1)qG3l>' );
define( 'NONCE_SALT',       '6G5),OeJKExg@Y/afY,SJ3J(JOhT?+%$r}w0AYel0fJsv<|(jtlOLWmqjKrN>W):' );
/**#@-*/

/**
 * Préfixe de base de données pour les tables de WordPress.
 *
 * Vous pouvez installer plusieurs WordPress sur une seule base de données
 * si vous leur donnez chacune un préfixe unique.
 * N’utilisez que des chiffres, des lettres non-accentuées, et des caractères soulignés !
 */
$table_prefix = 'wp_';

/**
 * Pour les développeurs : le mode déboguage de WordPress.
 *
 * En passant la valeur suivante à "true", vous activez l’affichage des
 * notifications d’erreurs pendant vos essais.
 * Il est fortemment recommandé que les développeurs d’extensions et
 * de thèmes se servent de WP_DEBUG dans leur environnement de
 * développement.
 *
 * Pour plus d’information sur les autres constantes qui peuvent être utilisées
 * pour le déboguage, rendez-vous sur le Codex.
 *
 * @link https://codex.wordpress.org/Debugging_in_WordPress
 */
define('WP_DEBUG', false);

/* C’est tout, ne touchez pas à ce qui suit ! Bonne publication. */

/** Chemin absolu vers le dossier de WordPress. */
if ( !defined('ABSPATH') )
	define('ABSPATH', dirname(__FILE__) . '/');

/** Réglage des variables de WordPress et de ses fichiers inclus. */
require_once(ABSPATH . 'wp-settings.php');
