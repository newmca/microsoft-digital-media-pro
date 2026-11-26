%{!?dmpkeys_version:%global dmpkeys_version 0.1.0}
%global app_id io.github.newmca.DmpKeys

Name:           dmpkeys
Version:        %{dmpkeys_version}
Release:        1%{?dist}
Summary:        Remap the special keys of the Microsoft Digital Media Pro Keyboard
License:        MIT
URL:            https://github.com/newmca/microsoft-digital-media-pro
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  appstream
BuildRequires:  libxml2

Requires:       python3-pyside6
Requires:       python3-jeepney
Requires:       polkit
Requires:       systemd-udev
Requires:       util-linux
Requires:       kmod

%description
Digital Media Pro Keys lets you choose what the special keys and the zoom
slider of the Microsoft Digital Media Pro Keyboard do. It repairs the five
My Favorites keys and writes the key mapping through a small root helper that
is authorised with polkit.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
# Runtime dependencies (PySide6, jeepney) are not needed to build the wheel.
%pyproject_buildrequires -R

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l dmpkeys

install -Dpm0755 src/dmpkeys/helper.py %{buildroot}%{_libexecdir}/%{name}/%{name}-helper
install -Dpm0644 data/%{app_id}.desktop %{buildroot}%{_datadir}/applications/%{app_id}.desktop
install -Dpm0644 data/%{app_id}.metainfo.xml %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
install -Dpm0644 data/%{app_id}.policy %{buildroot}%{_datadir}/polkit-1/actions/%{app_id}.policy
install -Dpm0644 data/icons/hicolor/scalable/apps/%{app_id}.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{app_id}.desktop
appstreamcli validate --no-net %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
xmllint --noout %{buildroot}%{_datadir}/polkit-1/actions/%{app_id}.policy

%files -f %{pyproject_files}
%{_bindir}/%{name}
%dir %{_libexecdir}/%{name}
%{_libexecdir}/%{name}/%{name}-helper
%{_datadir}/applications/%{app_id}.desktop
%{_metainfodir}/%{app_id}.metainfo.xml
%{_datadir}/polkit-1/actions/%{app_id}.policy
%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg

%changelog
* Wed Nov 25 2026 newmca <noreply@users.noreply.github.com> - 0.1.0-1
- First release
